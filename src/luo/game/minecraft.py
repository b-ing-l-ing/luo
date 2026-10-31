from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import Awaitable, Callable
from typing import Any

from websockets.asyncio.client import connect

from ..channels.base import BaseChannel, StopCompanion
from ..config import Settings
from ..core.interfaces import ChannelMessage

log = logging.getLogger("luo.mc")

MC_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "mc_follow",
            "description": (
                "让洛在 Minecraft 里跟着某个玩家。player 可选，"
                "默认跟着刚才说话的人。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "player": {"type": "string", "description": "玩家名，可选"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "mc_stop",
            "description": "让洛停止移动。",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "mc_goto",
            "description": "让洛走到指定坐标。",
            "parameters": {
                "type": "object",
                "properties": {
                    "x": {"type": "number"},
                    "y": {"type": "number"},
                    "z": {"type": "number"},
                },
                "required": ["x", "y", "z"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "mc_state",
            "description": "查看洛在游戏里的位置、血量、饥饿、背包和附近玩家。",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "mc_inventory",
            "description": "查看洛背包里有什么。",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "mc_collect",
            "description": (
                "在附近采集方块，例如木头、石头、沙子、泥土、煤矿。"
                "后台执行，做完会通知；不要等它。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "block": {
                        "type": "string",
                        "description": "方块名，例如 木头、石头、沙子",
                    },
                    "count": {
                        "type": "integer",
                        "description": "数量，默认 4，最多 16",
                    },
                },
                "required": ["block"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "mc_give",
            "description": (
                "把背包里的东西丢给玩家，会先走过去。"
                "后台执行，做完会通知。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "item": {
                        "type": "string",
                        "description": "物品名，例如 木头、煤、铁锭",
                    },
                    "count": {"type": "integer", "description": "数量，默认 1"},
                    "player": {
                        "type": "string",
                        "description": "玩家名，可选，默认给刚才说话的人",
                    },
                },
                "required": ["item"],
            },
        },
    },
]


def format_mc_event(
    name: str, data: dict[str, Any]
) -> tuple[str, str] | None:
    """把边车事件转成 (kind, text)；不认识的返回 None。"""
    username = str(data.get("username") or "").strip()
    if name == "death":
        position = data.get("position") or {}
        where = ""
        if position:
            try:
                where = (
                    f"（在 {float(position['x']):.0f}, "
                    f"{float(position['y']):.0f}, "
                    f"{float(position['z']):.0f}）"
                )
            except (KeyError, TypeError, ValueError):
                where = ""
        return "event", f"（游戏事件）洛在游戏里死了{where}。"
    if name == "player_death":
        if not username:
            return None
        return "event", f"（游戏事件）{username} 在游戏里死了。"
    if name == "spawn":
        return "event", "（游戏事件）洛进入了服务器。"
    if name == "player_joined":
        if not username:
            return None
        return "event", f"（游戏事件）{username} 进入了服务器。"
    if name == "player_left":
        if not username:
            return None
        return "event", f"（游戏事件）{username} 离开了服务器。"
    if name == "action_done":
        summary = str(data.get("summary") or "").strip()
        if not summary:
            return None
        return "action", summary
    if name == "action_failed":
        error = str(data.get("error") or "").strip() or "不知道为啥"
        return "action", f"没干成：{error}。"
    return None


def split_say(text: str, limit: int = 180) -> list[str]:
    text = text.strip()
    if not text:
        return []
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    while len(text) > limit:
        window = text[:limit]
        cut = max(
            window.rfind("\n"),
            window.rfind("。"),
            window.rfind("！"),
            window.rfind("？"),
            window.rfind("，"),
        )
        if cut < limit // 2:
            cut = limit - 1
        chunks.append(text[: cut + 1].strip())
        text = text[cut + 1 :].strip()
    if text:
        chunks.append(text)
    return [chunk for chunk in chunks if chunk]


COUNT_WORDS = {
    "一": 1,
    "两": 2,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}

COLLECT_BLOCKS = (
    "木头",
    "原木",
    "树",
    "橡木",
    "白桦",
    "云杉",
    "石头",
    "圆石",
    "泥土",
    "沙子",
    "煤矿",
    "铁矿",
    "铜矿",
    "金矿",
    "钻石",
)

GIVE_ITEMS = (
    "木头",
    "原木",
    "石头",
    "圆石",
    "泥土",
    "沙子",
    "煤",
    "铁锭",
    "面包",
    "苹果",
    "镐子",
    "斧子",
    "剑",
)


def parse_count(message: str, default: int = 4) -> int:
    match = re.search(r"(\d{1,2})", message)
    if match:
        return max(1, min(16, int(match.group(1))))
    for word, value in COUNT_WORDS.items():
        if f"{word}个" in message or f"{word}块" in message:
            return value
    return default


def parse_mc_intent(
    text: str, player: str
) -> tuple[str, dict[str, Any]] | None:
    message = text.split(": ", 1)[1] if ": " in text else text
    message = message.strip()
    if not message:
        return None
    # 去掉“洛，”“洛 ”之类称呼，只看指令本体。
    stripped = re.sub(r"^洛[，,、:：\s]*", "", message)
    if (
        any(
            word in message
            for word in (
                "别跟着",
                "别动",
                "停下",
                "停止",
                "别挖",
                "别采",
            )
        )
        or message in {"停", "stop"}
    ):
        return "mc_stop", {}
    # “跟我讲个故事”不是指令，“跟我来/过来”才是。
    if "跟着我" in message or re.match(
        r"^(快|来|你)?\s*(跟我来|跟我走|跟我这边|跟我$|过来|跟上)",
        stripped,
    ):
        return "mc_follow", {"player": player}
    if any(
        word in message
        for word in ("你在哪", "你在哪里", "什么状态", "坐标")
    ):
        return "mc_state", {}
    if any(
        word in message
        for word in ("背包", "带了什么", "有什么东西")
    ):
        return "mc_inventory", {}
    # 必须是命令式的“挖/砍/采”，不能把“今天挖了木头”这种闲聊当指令。
    collect_cmd = re.match(
        r"^(快|去|帮我|帮忙|给我|来)?\s*(挖|砍|采)(?!了)",
        stripped,
    ) or re.search(r"(帮我|帮忙|去|快)\s*(挖|砍|采)(?!了)", stripped)
    if collect_cmd:
        for block in COLLECT_BLOCKS:
            if block in stripped:
                return "mc_collect", {
                    "block": block,
                    "count": parse_count(stripped),
                }
    # “他给了我木头”不是指令；必须以“给我/送我/扔给”开头。
    give_cmd = re.match(
        r"^(能|可以|麻烦)?\s*(给我|送我|扔给)", stripped
    )
    if give_cmd:
        for item in GIVE_ITEMS:
            if item in stripped:
                return "mc_give", {
                    "item": item,
                    "count": parse_count(stripped, 1),
                    "player": player,
                }
    return None


class MinecraftChannel(BaseChannel):
    """通过 Node 边车的本地 WebSocket API 和游戏交互。"""

    name = "mc"
    supports_images = False

    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self.url = settings.mc_ws_url.strip()
        self.bot_name = settings.mc_bot_name.strip() or "LuoBot"
        self.allowed = {
            item.strip()
            for item in settings.mc_allowed_players.split(",")
            if item.strip()
        }
        self._ws = None
        self._stop = asyncio.Event()
        self._send_lock = asyncio.Lock()
        self._pending: dict[str, asyncio.Future] = {}
        self._echo = 0
        self._last_speaker = ""

    async def open(self) -> None:
        if not self.url:
            raise RuntimeError("MC_WS_URL 未配置")

    async def start(
        self, on_message: Callable[[ChannelMessage], Awaitable[None]]
    ) -> None:
        backoff = 1.0
        while not self._stop.is_set():
            try:
                async with connect(self.url, max_size=2**24) as ws:
                    self._ws = ws
                    backoff = 1.0
                    log.info("MC 已连接：%s", self.url)
                    queue: asyncio.Queue[ChannelMessage] = asyncio.Queue()

                    async def worker() -> None:
                        while True:
                            msg = await queue.get()
                            try:
                                await on_message(msg)
                            except StopCompanion:
                                self._stop.set()
                                await ws.close()
                                return
                            except Exception:  # noqa: BLE001
                                log.exception("处理 MC 消息失败")

                    worker_task = asyncio.create_task(worker())
                    try:
                        async for raw in ws:
                            if self._stop.is_set():
                                break
                            try:
                                event = json.loads(raw)
                            except json.JSONDecodeError:
                                continue
                            if event.get("type") == "result":
                                future = self._pending.get(
                                    event.get("id")
                                )
                                if future is not None and not future.done():
                                    future.set_result(event)
                                continue
                            if event.get("type") != "event":
                                continue
                            name = str(event.get("event") or "")
                            data = event.get("data") or {}
                            if name == "chat":
                                username = str(
                                    data.get("username") or ""
                                ).strip()
                                message = str(
                                    data.get("message") or ""
                                ).strip()
                                if (
                                    not username
                                    or not message
                                    or username == self.bot_name
                                ):
                                    continue
                                if (
                                    self.allowed
                                    and username not in self.allowed
                                ):
                                    continue
                                self._last_speaker = username
                                await queue.put(
                                    ChannelMessage(
                                        channel="mc",
                                        user_id="local",
                                        text=f"{username}: {message}",
                                        display_name=username,
                                    )
                                )
                                continue
                            formatted = format_mc_event(name, data)
                            if formatted is None:
                                continue
                            kind, text = formatted
                            await queue.put(
                                ChannelMessage(
                                    channel="mc",
                                    user_id="local",
                                    text=text,
                                    display_name=None,
                                    kind=kind,
                                )
                            )
                    finally:
                        worker_task.cancel()
                        try:
                            await worker_task
                        except asyncio.CancelledError:
                            pass
            except StopCompanion:
                raise
            except Exception as exc:  # noqa: BLE001
                if self._stop.is_set():
                    break
                log.warning(
                    "MC 连接断开：%s，%ss 后重连", exc, int(backoff)
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)
            finally:
                self._ws = None
        raise StopCompanion

    async def call(
        self, skill: str, args: dict[str, Any]
    ) -> dict[str, Any]:
        if self._ws is None:
            raise RuntimeError("MC 未连接")
        self._echo += 1
        request_id = f"mc-{self._echo}"
        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()
        self._pending[request_id] = future
        payload = {
            "type": "call",
            "id": request_id,
            "skill": skill,
            "args": args,
        }
        try:
            async with self._send_lock:
                await self._ws.send(
                    json.dumps(payload, ensure_ascii=False)
                )
            result = await asyncio.wait_for(future, 15)
        finally:
            self._pending.pop(request_id, None)
        if not result.get("ok"):
            raise RuntimeError(result.get("error") or "MC 调用失败")
        return result.get("data") or {}

    def game_tools(self) -> list[dict[str, Any]]:
        return MC_TOOLS

    async def execute_skill(
        self, name: str, args: dict[str, Any]
    ) -> str:
        skill = name[3:] if name.startswith("mc_") else name
        if skill == "follow":
            player = str(
                args.get("player") or self._last_speaker
            ).strip()
            if not player:
                return "不知道要跟谁。"
            data = await self.call("follow", {"player": player})
            return f"正在跟着 {data.get('player', player)}。"
        if skill == "stop":
            await self.call("stop", {})
            return "停下了。"
        if skill == "goto":
            data = await self.call(
                "goto",
                {
                    "x": args.get("x"),
                    "y": args.get("y"),
                    "z": args.get("z"),
                },
            )
            position = data.get("position") or {}
            return (
                f"去 {position.get('x')}, {position.get('y')}, "
                f"{position.get('z')}。"
            )
        if skill == "state":
            data = await self.call("state", {})
            if not data.get("spawned"):
                return "洛还没进服。"
            position = data.get("position") or {}
            players = data.get("players") or []
            inventory = data.get("inventory") or []
            items = "、".join(
                f"{item.get('name')}x{item.get('count')}"
                for item in inventory[:6]
            )
            return (
                f"在 {position.get('x'):.1f}, {position.get('y'):.1f}, "
                f"{position.get('z'):.1f}，血量 {data.get('health')}，"
                f"饥饿 {data.get('food')}，附近玩家："
                f"{'、'.join(players) if players else '没有'}，"
                f"背包：{items or '空'}"
            )
        if skill == "inventory":
            data = await self.call("inventory", {})
            items = data.get("items") or []
            if not items:
                return "背包是空的。"
            text = "、".join(
                f"{item.get('name')}x{item.get('count')}"
                for item in items[:12]
            )
            total = int(data.get("total") or len(items))
            if total > len(items[:12]):
                text += f" 等 {total} 种"
            return f"背包：{text}"
        if skill == "collect":
            block = str(args.get("block") or "").strip()
            if not block:
                return "没说挖什么。"
            count = int(args.get("count") or 4)
            await self.call(
                "collect",
                {"block": block, "count": max(1, min(16, count))},
            )
            return f"去挖{block}了。"
        if skill == "give":
            player = str(
                args.get("player") or self._last_speaker
            ).strip()
            item = str(args.get("item") or "").strip()
            if not player:
                return "不知道给谁。"
            if not item:
                return "没说给什么。"
            count = int(args.get("count") or 1)
            await self.call(
                "give",
                {
                    "player": player,
                    "item": item,
                    "count": max(1, count),
                },
            )
            return f"去给 {player} 送{item}了。"
        return f"未知游戏技能：{name}"

    async def send(self, to: str, text: str) -> None:
        for chunk in split_say(text):
            await self.call("say", {"text": chunk})

    async def send_image(self, to: str, data: bytes, mime: str) -> None:
        raise RuntimeError("Minecraft 通道不支持图片")

    async def stop(self) -> None:
        self._stop.set()
        ws = self._ws
        self._ws = None
        if ws is not None:
            try:
                await ws.close()
            except Exception:  # noqa: BLE001
                pass
