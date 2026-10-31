from __future__ import annotations

import asyncio
import json
import logging
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
]


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


def parse_mc_intent(
    text: str, player: str
) -> tuple[str, dict[str, Any]] | None:
    message = text.split(": ", 1)[1] if ": " in text else text
    message = message.strip()
    if not message:
        return None
    if (
        any(word in message for word in ("别跟着", "别动", "停下", "停止"))
        or message in {"停", "stop"}
    ):
        return "mc_stop", {}
    if any(word in message for word in ("跟着我", "跟我", "过来", "跟上")):
        return "mc_follow", {"player": player}
    if any(
        word in message
        for word in ("你在哪", "你在哪里", "什么状态", "状态", "坐标")
    ):
        return "mc_state", {}
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
                            if event.get("event") != "chat":
                                continue
                            data = event.get("data") or {}
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
            return (
                f"在 {position.get('x'):.1f}, {position.get('y'):.1f}, "
                f"{position.get('z'):.1f}，血量 {data.get('health')}，"
                f"饥饿 {data.get('food')}，附近玩家："
                f"{'、'.join(players) if players else '没有'}"
            )
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
