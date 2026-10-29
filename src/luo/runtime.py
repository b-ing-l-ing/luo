from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from .chat import build_messages, load_persona
from .channels.base import StopCompanion
from .config import Settings
from .core.interfaces import ChannelMessage, ChatChannel
from .greeting import greet
from .images import (
    fetch_image_data_url,
    image_dimensions,
    is_save_request,
    parse_data_url,
    save_data_url,
)
from .llm import AsyncChatLLM, ChatLLM
from .memes import MemeLibrary, SEND_MEME_TOOL
from .memory import MemoryManager, summarize_session
from .search import SEND_WEB_MEME_TOOL, WEB_SEARCH_TOOL, SearchClient
from .stickers import (
    ANNOTATE_STICKERS_TOOL,
    LIST_STICKERS_TOOL,
    SEND_STICKER_TOOL,
    StickerLibrary,
    parse_annotation,
)
from .store import Store
from .style import find_violations

log = logging.getLogger("luo.runtime")


def parse_aliases(raw: str) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for item in raw.split(","):
        if "=" not in item:
            continue
        src, dst = item.split("=", 1)
        src, dst = src.strip(), dst.strip()
        if src and dst:
            aliases[src] = dst
    return aliases


def map_session_key(
    channel: str, user_id: str, aliases: dict[str, str]
) -> str:
    # 终端沿用旧的 "local"，避免已有记忆/历史在升级后“消失”。
    raw = user_id if channel == "terminal" else f"{channel}:{user_id}"
    return aliases.get(raw, raw)


HELP_TEXT = """命令
  /quit /exit       退出
  /reset            清空本会话的事件、记忆和摘要
  /memory           查看记忆
  /done <id>        把一条记忆标记为完成
  /forget <id>      删除一条记忆
  /remember <内容>  手动记一条事实
  /promise <内容>   手动记一条没做完的事
  /summary          查看最近的会话摘要
  /meme <标签>      发一张本地梗图，例如 /meme 无语
  /stickers [关键词] 同步/查看 QQ 收藏表情
  /annotate [数量]  看图给收藏表情补描述/标签
  /sticker <id/描述> 发一张 QQ 收藏表情
  /webmeme <搜索词> 联网搜一张梗图并自动存库
  /save [标签]      把最近收到的图存进 memes/，可带标签
  /help             显示这个帮助"""


class Session:
    """一个用户在一个通道里的完整状态。"""

    def __init__(
        self,
        store: Store,
        sync_llm: ChatLLM,
        settings: Settings,
        channel: str,
        user_id: str,
        key: str,
    ) -> None:
        self.store = store
        self.sync_llm = sync_llm
        self.settings = settings
        self.channel = channel
        self.user_id = user_id
        self.key = key
        self.last_activity = time.monotonic()
        self.last_proactive_at = 0.0
        self.recent_images: list[str] = []
        self.persona = load_persona(settings.persona_path)
        self.last_summaries = store.recent_session_summaries(self.key, 1)
        if self.last_summaries:
            self.persona = (
                f"{self.persona}\n\n【上次你们聊到】\n"
                f"{self.last_summaries[0]['summary']}"
            )
        self.session_start_event_id = store.last_event_id(self.key)
        self.history = store.recent_events(self.key, settings.history_limit)
        self.memory = MemoryManager(store, sync_llm, settings, self.key)
        self.open_loops = [
            str(item["content"]) for item in store.open_memories(self.key, 5)
        ]

    def reset(self) -> None:
        self.store.reset_session(self.key)
        self.history.clear()
        self.recent_images = []
        self.persona = load_persona(self.settings.persona_path)
        self.last_summaries = []
        self.session_start_event_id = 0
        self.memory = MemoryManager(
            self.store, self.sync_llm, self.settings, self.key
        )
        self.open_loops = []

    def refresh_open_loops(self) -> None:
        self.open_loops = [
            str(item["content"]) for item in self.store.open_memories(self.key, 5)
        ]


class CompanionRuntime:
    def __init__(
        self,
        settings: Settings,
        channel: ChatChannel,
        *,
        store: Store | None = None,
        sync_llm: ChatLLM | None = None,
        async_llm: AsyncChatLLM | None = None,
    ) -> None:
        self.settings = settings
        self.channel = channel
        self.store = store or Store(settings.db_path)
        self.sync_llm = sync_llm or ChatLLM(settings)
        self.async_llm = async_llm or AsyncChatLLM(settings)
        self.aliases = parse_aliases(settings.session_aliases)
        self.search = SearchClient(settings) if settings.web_search_enabled else None
        self.memes = MemeLibrary(settings.memes_dir)
        self.stickers = StickerLibrary(settings.stickers_path)
        self._web_meme_times: list[float] = []
        self.sessions: dict[str, Session] = {}

    def _get_session(self, channel: str, user_id: str) -> Session:
        key = map_session_key(channel, user_id, self.aliases)
        if key not in self.sessions:
            self.sessions[key] = Session(
                self.store, self.sync_llm, self.settings, channel, user_id, key
            )
        return self.sessions[key]

    async def run(self) -> None:
        proactive: asyncio.Task | None = None
        try:
            await self.channel.open()
            proactive = asyncio.create_task(self._proactive_loop())
            if self.channel.name == "terminal":
                session = self._get_session("terminal", "local")
                await self.channel.send("local", "洛 v0.7  /help 查看命令")
                if session.history:
                    await self.channel.send(
                        "local", f"已载入最近 {len(session.history)} 条消息"
                    )
                if session.last_summaries:
                    await self.channel.send("local", "已载入上次会话摘要")
                await self._greet(session)
            await self.channel.start(self.on_message)
        except StopCompanion:
            pass
        finally:
            if proactive is not None:
                proactive.cancel()
                try:
                    await proactive
                except asyncio.CancelledError:
                    pass
            await self.shutdown()

    async def _greet(self, session: Session) -> None:
        if not self.settings.startup_greeting:
            return
        if not (session.last_summaries or session.open_loops):
            return
        try:
            text = await asyncio.to_thread(
                greet,
                self.sync_llm,
                self.store,
                session.persona,
                session.open_loops,
                emit=lambda _: None,
                session_id=session.key,
            )
        except Exception as exc:  # noqa: BLE001
            await self._safe_send(session.user_id, f"主动开口失败：{exc}")
            return
        if not text:
            return
        await self.channel.start_message(session.user_id)
        await self.channel.send_delta(session.user_id, text)
        await self.channel.end_message(session.user_id)
        session.history.append({"role": "assistant", "content": text})
        await self._style_check(session.user_id, text)

    async def on_message(self, msg: ChannelMessage) -> None:
        text = msg.text.strip()
        if not text and not msg.images:
            return
        session = self._get_session(msg.channel, msg.user_id)
        session.last_activity = time.monotonic()
        if msg.images:
            session.recent_images = [
                *session.recent_images,
                *msg.images,
            ][-3:]

        if text in {"/quit", "/exit"}:
            raise StopCompanion
        if text == "/reset":
            session.reset()
            await self.channel.send(msg.user_id, "已清空本会话的事件、记忆和摘要")
            return
        if text == "/memory":
            rows = session.store.all_memories(session.key, limit=100)
            if not rows:
                await self.channel.send(msg.user_id, "还没有记忆")
            for row in rows:
                state = "未完成" if row["status"] == "open" else "已归档"
                await self.channel.send(
                    msg.user_id,
                    f"{row['id']}. ({row['kind']}|{state}) {row['content']} "
                    f"重要度{row['importance']} {str(row['ts'])[:10]}",
                )
            return
        if text == "/help":
            await self.channel.send(msg.user_id, HELP_TEXT)
            return
        if text == "/summary":
            rows = session.store.recent_session_summaries(session.key, 3)
            if not rows:
                await self.channel.send(msg.user_id, "还没有会话摘要")
            for row in rows:
                await self.channel.send(
                    msg.user_id, f"{str(row['ended_at'])[:16]} {row['summary']}"
                )
            return
        if text.startswith("/remember "):
            content = text[len("/remember ") :].strip()
            if not content:
                await self.channel.send(msg.user_id, "用法：/remember <内容>")
                return
            session.store.add_memory(
                session.key, "fact", content[:300], 4, status="closed"
            )
            await self.channel.send(msg.user_id, "已记住")
            return
        if text.startswith("/promise "):
            content = text[len("/promise ") :].strip()
            if not content:
                await self.channel.send(msg.user_id, "用法：/promise <内容>")
                return
            session.store.add_memory(
                session.key, "promise", content[:300], 4, status="open"
            )
            session.refresh_open_loops()
            await self.channel.send(msg.user_id, "已记下")
            return
        if text.startswith("/done"):
            parts = text.split()
            if len(parts) != 2 or not parts[1].isdigit():
                await self.channel.send(msg.user_id, "用法：/done <id>")
                return
            done = session.store.set_memory_status(int(parts[1]), "closed")
            await self.channel.send(
                msg.user_id, "已标记完成" if done else "没找到这条记忆"
            )
            session.refresh_open_loops()
            return
        if text.startswith("/forget"):
            parts = text.split()
            if len(parts) != 2 or not parts[1].isdigit():
                await self.channel.send(msg.user_id, "用法：/forget <id>")
                return
            deleted = session.store.delete_memory(int(parts[1]))
            await self.channel.send(
                msg.user_id, "已删除" if deleted else "没找到这条记忆"
            )
            session.refresh_open_loops()
            return
        if text == "/save" or text.startswith("/save "):
            tag = text[len("/save") :].strip() or None
            await self.channel.send(
                msg.user_id, self._save_last_image(session, tag)
            )
            return
        save_tag = is_save_request(text)
        if save_tag is not None:
            await self.channel.send(
                msg.user_id,
                self._save_last_image(session, save_tag or None),
            )
            return
        if text == "/stickers" or text.startswith("/stickers "):
            query = text[len("/stickers") :].strip()
            result = await self._execute_tool(
                "list_stickers",
                json.dumps({"query": query}, ensure_ascii=False),
                to=msg.user_id,
            )
            await self.channel.send(msg.user_id, result)
            return
        if text == "/annotate" or text.startswith("/annotate "):
            count_text = text[len("/annotate") :].strip()
            payload = (
                {"count": int(count_text)}
                if count_text.isdigit()
                else {}
            )
            result = await self._execute_tool(
                "annotate_stickers",
                json.dumps(payload, ensure_ascii=False),
                to=msg.user_id,
            )
            await self.channel.send(msg.user_id, result)
            return
        if text == "/sticker" or text.startswith("/sticker "):
            ref = text[len("/sticker") :].strip()
            if not ref:
                await self.channel.send(
                    msg.user_id, "用法：/sticker <id 或描述>"
                )
                return
            result = await self._execute_tool(
                "send_sticker",
                json.dumps({"ref": ref}, ensure_ascii=False),
                to=msg.user_id,
            )
            await self.channel.send(msg.user_id, result)
            return
        if text == "/webmeme" or text.startswith("/webmeme "):
            query = text[len("/webmeme") :].strip()
            if not query:
                await self.channel.send(
                    msg.user_id,
                    "用法：/webmeme <搜索词>，例如 /webmeme 无语 表情包",
                )
                return
            result = await self._execute_tool(
                "send_web_meme",
                json.dumps({"query": query}, ensure_ascii=False),
                to=msg.user_id,
            )
            await self.channel.send(msg.user_id, result)
            return
        if text == "/meme" or text.startswith("/meme "):
            query = text[len("/meme") :].strip()
            if not query:
                await self.channel.send(
                    msg.user_id, "用法：/meme <标签>，例如 /meme 无语"
                )
                return
            result = await self._execute_tool(
                "send_meme",
                json.dumps({"query": query}, ensure_ascii=False),
                to=msg.user_id,
            )
            await self.channel.send(msg.user_id, result)
            return

        await self.handle_chat(session, msg)

    async def handle_chat(self, session: Session, msg: ChannelMessage) -> None:
        text = msg.text.strip() or ("（图片）" if msg.images else "")
        session.store.add_event(session.key, "user", text)
        memory_block = session.memory.render_for(text)
        messages = build_messages(
            session.persona, memory_block, session.history, text, msg.images
        )

        tools: list[dict[str, Any]] = []
        if self.search is not None:
            tools.append(WEB_SEARCH_TOOL)
            tools.append(SEND_WEB_MEME_TOOL)
        if self.memes.tags():
            tools.append(SEND_MEME_TOOL)
        if hasattr(self.channel, "fetch_custom_faces"):
            tools.append(LIST_STICKERS_TOOL)
            tools.append(SEND_STICKER_TOOL)
            tools.append(ANNOTATE_STICKERS_TOOL)

        async def execute_tool(name: str, arguments: str) -> str:
            return await self._execute_tool(name, arguments, to=msg.user_id)

        parts: list[str] = []
        await self.channel.start_message(msg.user_id)
        try:
            if tools:
                stream = self.async_llm.stream_with_tools(
                    messages, tools, execute_tool
                )
            else:
                stream = self.async_llm.stream(messages)
            async for delta in stream:
                parts.append(delta)
                await self.channel.send_delta(msg.user_id, delta)
        except Exception as exc:  # noqa: BLE001
            await self.channel.end_message(msg.user_id)
            await self._safe_send(msg.user_id, f"模型调用失败：{exc}")
            return
        await self.channel.end_message(msg.user_id)

        reply = "".join(parts).strip()
        if reply:
            session.store.add_event(session.key, "assistant", reply)
            session.history.extend(
                [
                    {"role": "user", "content": text},
                    {"role": "assistant", "content": reply},
                ]
            )
            limit = self.settings.history_limit
            if limit > 0 and len(session.history) > limit:
                del session.history[:-limit]
            session.last_activity = time.monotonic()
        await self._style_check(msg.user_id, reply)

        try:
            await asyncio.to_thread(session.memory.on_turn)
            if session.memory.last_resolved:
                await self._safe_send(
                    msg.user_id,
                    f"记忆整理：完成 {len(session.memory.last_resolved)} 条",
                )
        except Exception as exc:  # noqa: BLE001
            await self._safe_send(msg.user_id, f"记忆抽取失败：{exc}")

    def _save_last_image(self, session: Session, tag: str | None) -> str:
        if not session.recent_images:
            return "最近没收到图，先发一张再存。"
        path = save_data_url(
            session.recent_images[-1], self.settings.memes_dir, tag
        )
        if path is None:
            return "这张图存失败，可能格式不支持。"
        return f"存好了：{path.name}"

    async def _execute_tool(
        self, name: str, arguments: str, *, to: str
    ) -> str:
        try:
            args = json.loads(arguments or "{}")
        except json.JSONDecodeError:
            return "工具参数不是合法 JSON。"

        if name == "list_stickers":
            fetch = getattr(self.channel, "fetch_custom_faces", None)
            if fetch is None:
                return "当前通道不支持 QQ 收藏表情。"
            try:
                count = max(1, min(int(args.get("limit") or 100), 200))
            except (TypeError, ValueError):
                count = 100
            try:
                fetched = await fetch(count)
            except Exception as exc:  # noqa: BLE001
                return f"同步收藏表情失败：{exc}"
            added = self.stickers.merge(fetched)
            query = str(args.get("query", "")).strip()
            try:
                limit = max(1, min(int(args.get("limit") or 20), 100))
            except (TypeError, ValueError):
                limit = 20
            entries = self.stickers.list(query, limit)
            if not entries:
                return (
                    "QQ 收藏表情是空的。先在机器人小号里收藏几张表情，"
                    "再让我同步。"
                )
            text = "QQ 收藏表情：\n" + "\n".join(
                entry.label() for entry in entries
            )
            if added:
                text += f"\n（新增 {added} 个）"
            missing = sum(
                1
                for entry in self.stickers.entries
                if not entry.desc and not entry.note
            )
            if missing:
                text += (
                    f"\n（还有 {missing} 个没备注，"
                    "可以调用 annotate_stickers 看图补）"
                )
            return text

        if name == "annotate_stickers":
            fetch = getattr(self.channel, "fetch_custom_faces", None)
            if fetch is None:
                return "当前通道不支持 QQ 收藏表情。"
            try:
                self.stickers.merge(await fetch(200))
            except Exception as exc:  # noqa: BLE001
                return f"同步收藏表情失败：{exc}"
            try:
                count = max(1, min(int(args.get("count") or 3), 10))
            except (TypeError, ValueError):
                count = 3
            entries = self.stickers.missing_note(count)
            if not entries:
                return "没有需要整理的表情。"
            results: list[str] = []
            for entry in entries:
                data_url = await asyncio.to_thread(
                    fetch_image_data_url, entry.url
                )
                if not data_url:
                    continue
                messages = [
                    {
                        "role": "system",
                        "content": (
                            "你是表情包整理器。看图片，用不超过 15 个字"
                            "描述它表达的情绪/场景，并给 2-4 个标签。"
                            '只输出 JSON：{"note":"...","tags":["..."]}，'
                            "不要其他文字。"
                        ),
                    },
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": "这张表情包是什么？",
                            },
                            {
                                "type": "image_url",
                                "image_url": {"url": data_url},
                            },
                        ],
                    },
                ]
                try:
                    raw = await self.async_llm.complete(
                        messages, json_mode=True
                    )
                except Exception as exc:  # noqa: BLE001
                    results.append(f"{entry.id}: 失败 {exc}")
                    continue
                note, tags = parse_annotation(raw)
                if not note:
                    note = raw.strip()[:60]
                if not note:
                    continue
                self.stickers.set_note(entry, note, tags)
                results.append(f"{entry.id}: {note}")
            if not results:
                return "没整理成功，图片下载可能失败。"
            return "已整理：\n" + "\n".join(results)

        if name == "send_sticker":
            ref = str(args.get("ref", "")).strip()
            if not ref:
                return "缺少 ref 参数。"
            entry = self.stickers.find(ref)
            if entry is None:
                fetch = getattr(self.channel, "fetch_custom_faces", None)
                if fetch is not None:
                    try:
                        self.stickers.merge(await fetch(200))
                    except Exception:  # noqa: BLE001
                        pass
                    entry = self.stickers.find(ref)
            if entry is None:
                return (
                    "没找到这个表情；先用 list_stickers 查 id/描述，"
                    "没备注可以用 annotate_stickers 看图补。"
                )
            data_url = await asyncio.to_thread(
                fetch_image_data_url, entry.url
            )
            if not data_url:
                return "表情图片下载失败，可能地址过期；同步一次再试。"
            parsed = parse_data_url(data_url)
            if parsed is None:
                return "表情图片格式不支持。"
            data, mime = parsed
            try:
                await self.channel.send_image(to, data, mime)
            except Exception as exc:  # noqa: BLE001
                return f"发送表情失败：{exc}"
            self.stickers.mark_used(entry)
            return f"已发送表情：{entry.desc or entry.id}"

        if name == "send_meme":
            query = str(args.get("query", "")).strip()
            path = self.memes.find(query)
            if path is None:
                tags = self.memes.tags()
                if not tags:
                    return (
                        "本地梗图库是空的。把图片放进 memes/，"
                        "文件名就是标签，例如 无语.png。"
                    )
                return "没有匹配的梗图。可用标签：" + "、".join(tags[:20])
            try:
                data = path.read_bytes()
            except OSError as exc:
                return f"读取梗图失败：{exc}"
            if len(data) > 2 * 1024 * 1024:
                return "这张梗图超过 2MB，QQ 发送限制，换一张。"
            try:
                await self.channel.send_image(
                    to, data, self.memes.mime_for(path)
                )
            except Exception as exc:  # noqa: BLE001
                return f"发送梗图失败：{exc}"
            return f"已发送梗图：{path.stem}"

        if name == "send_web_meme":
            query = str(args.get("query", "")).strip()
            if not query:
                return "缺少 query 参数。"
            if self.search is None:
                return "联网搜索未启用。"
            now = time.monotonic()
            self._web_meme_times = [
                stamp for stamp in self._web_meme_times if now - stamp < 3600
            ]
            if len(self._web_meme_times) >= self.settings.web_meme_max_per_hour:
                return "这一小时搜图次数到上限了，先用本地梗图。"
            try:
                results = await asyncio.to_thread(
                    self.search.search_images, query
                )
            except Exception as exc:  # noqa: BLE001
                return f"搜图失败：{exc}"
            if not results:
                return "没搜到合适的图。"
            tag = str(args.get("tag", "")).strip() or query
            for result in results[:5]:
                data_url = await asyncio.to_thread(
                    fetch_image_data_url, result.url
                )
                if not data_url:
                    continue
                parsed = parse_data_url(data_url)
                if parsed is None:
                    continue
                data, mime = parsed
                if len(data) > 2 * 1024 * 1024 or len(data) < 4096:
                    continue
                dimensions = image_dimensions(data)
                if dimensions is not None and (
                    dimensions[0] < 120 or dimensions[1] < 120
                ):
                    continue
                try:
                    await self.channel.send_image(to, data, mime)
                except Exception as exc:  # noqa: BLE001
                    return f"发送网图失败：{exc}"
                self._web_meme_times.append(now)
                saved = ""
                if (
                    self.settings.auto_save_web_memes
                    and not self.memes.has_same_content(data)
                ):
                    path = save_data_url(
                        data_url, self.settings.memes_dir, tag
                    )
                    if path is not None:
                        saved = f"，已存为 {path.name}"
                if saved:
                    return f"已发送网图{saved}"
                return "已发送网图。"
            return "搜到了图，但下载都失败了。"

        if name == "web_search":
            query = str(args.get("query", "")).strip()
            if not query:
                return "缺少 query 参数。"
            if self.search is None:
                return "联网搜索未启用。"
            try:
                response = await asyncio.to_thread(
                    self.search.search, query
                )
            except Exception as exc:  # noqa: BLE001
                return f"搜索失败：{exc}"
            return self.search.format_results(response)

        return f"未知工具：{name}"

    async def _style_check(self, to: str, text: str) -> None:
        if not self.settings.style_debug or not text:
            return
        hits = find_violations(text)
        if hits:
            await self._safe_send(to, f"AI味：{'、'.join(hits)}")

    async def _safe_send(self, to: str, text: str) -> None:
        try:
            await self.channel.send(to, text)
        except Exception:  # noqa: BLE001 - 发送失败不应该拖垮运行时
            pass

    async def _proactive_loop(self) -> None:
        while True:
            await asyncio.sleep(self.settings.proactive_check_seconds)
            try:
                await self.proactive_once()
            except Exception:  # noqa: BLE001
                log.exception("主动消息检查失败")

    async def proactive_once(self) -> list[tuple[str, str]]:
        if not self.settings.proactive_enabled:
            return []
        now = time.monotonic()
        sent: list[tuple[str, str]] = []
        for session in list(self.sessions.values()):
            if session.channel != "qq":
                continue
            session.refresh_open_loops()
            if not session.open_loops:
                continue
            if now - session.last_activity < self.settings.proactive_idle_minutes * 60:
                continue
            if (
                session.last_proactive_at
                and now - session.last_proactive_at
                < self.settings.proactive_cooldown_minutes * 60
            ):
                continue
            session.last_proactive_at = now
            text = await self._compose_proactive(session)
            if not text:
                continue
            await self.channel.send(session.user_id, text)
            session.store.add_event(session.key, "assistant", text)
            session.last_activity = now
            sent.append((session.user_id, text))
        return sent

    async def _compose_proactive(self, session: Session) -> str:
        loops = "\n".join(f"- {item}" for item in session.open_loops[:5])
        system = (
            f"{session.persona}\n\n【还没做完的事】\n{loops}\n\n"
            "你们已经有一阵没说话了。如果自然，就发一句不超过 20 字的跟进；"
            "不要客套，不要问“在吗”，不要说“根据记忆/记录”。"
            "不想说就只输出 [SILENT]。"
        )
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": "（现在轮到你先开口）"},
        ]
        raw = await self.async_llm.complete(messages)
        text = raw.strip()
        if not text or "[SILENT]" in text:
            return ""
        return text[:100]

    async def shutdown(self) -> None:
        for session in self.sessions.values():
            try:
                added = await asyncio.to_thread(session.memory.flush)
                if added:
                    await self._safe_send(
                        session.user_id, f"记忆整理：新增 {len(added)} 条"
                    )
                if session.memory.last_resolved:
                    await self._safe_send(
                        session.user_id,
                        f"记忆整理：完成 {len(session.memory.last_resolved)} 条",
                    )
            except Exception as exc:  # noqa: BLE001
                await self._safe_send(session.user_id, f"记忆整理失败：{exc}")

            try:
                events = session.store.events_after(
                    session.key, session.session_start_event_id
                )
                if events:
                    summary = await asyncio.to_thread(
                        summarize_session, self.sync_llm, events
                    )
                    if summary:
                        session.store.add_session_summary(
                            session.key,
                            str(events[0]["ts"]),
                            len(events),
                            summary,
                        )
                        await self._safe_send(
                            session.user_id, "会话摘要：已保存"
                        )
            except Exception as exc:  # noqa: BLE001
                await self._safe_send(session.user_id, f"会话摘要失败：{exc}")

        try:
            await self.channel.stop()
        finally:
            self.store.close()
