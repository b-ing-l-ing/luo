from __future__ import annotations

import asyncio
import logging
import time

from .chat import build_messages, load_persona
from .channels.base import StopCompanion
from .config import Settings
from .core.interfaces import ChannelMessage, ChatChannel
from .greeting import greet
from .llm import AsyncChatLLM, ChatLLM
from .memory import MemoryManager, summarize_session
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
                await self.channel.send("local", "洛 v0.6  /help 查看命令")
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
        if not text:
            return
        session = self._get_session(msg.channel, msg.user_id)
        session.last_activity = time.monotonic()

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

        await self.handle_chat(session, msg)

    async def handle_chat(self, session: Session, msg: ChannelMessage) -> None:
        text = msg.text.strip()
        session.store.add_event(session.key, "user", text)
        memory_block = session.memory.render_for(text)
        messages = build_messages(
            session.persona, memory_block, session.history, text
        )

        parts: list[str] = []
        await self.channel.start_message(msg.user_id)
        try:
            async for delta in self.async_llm.stream(messages):
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
