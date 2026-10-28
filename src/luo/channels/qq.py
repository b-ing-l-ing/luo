from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

from ..config import Settings
from ..core.interfaces import ChannelMessage
from .base import BaseChannel, StopCompanion

log = logging.getLogger("luo.qq")


def parse_allowed(raw: str) -> set[str]:
    return {item.strip() for item in raw.split(",") if item.strip()}


def extract_text(event: dict[str, Any]) -> str:
    message = event.get("message")
    if isinstance(message, str):
        return message.strip()
    if isinstance(message, list):
        parts: list[str] = []
        for segment in message:
            if not isinstance(segment, dict):
                continue
            kind = segment.get("type")
            data = segment.get("data") or {}
            if kind == "text":
                text = data.get("text")
                if text:
                    parts.append(str(text))
            elif kind == "image":
                parts.append("[图片]")
            elif kind == "face":
                parts.append("[表情]")
            elif kind == "record":
                parts.append("[语音]")
            elif kind == "file":
                parts.append("[文件]")
        return "".join(parts).strip()
    raw = event.get("raw_message")
    return str(raw).strip() if raw else ""


def split_message(text: str, limit: int = 400) -> list[str]:
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
            window.rfind("；"),
        )
        if cut < limit // 2:
            cut = limit - 1
        chunks.append(text[: cut + 1].strip())
        text = text[cut + 1 :].strip()
    if text:
        chunks.append(text)
    return [chunk for chunk in chunks if chunk]


def build_send_payload(user_id: str, text: str, echo: str) -> dict[str, Any]:
    return {
        "action": "send_private_msg",
        "params": {
            "user_id": int(user_id),
            "message": [{"type": "text", "data": {"text": text}}],
        },
        "echo": echo,
    }


class QQChannel(BaseChannel):
    """OneBot 11 私聊通道。只处理白名单用户的 private 消息。"""

    name = "qq"

    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self.url = settings.qq_ws_url.strip()
        self.token = settings.qq_access_token.strip()
        self.allowed = parse_allowed(settings.qq_allowed_users)
        self.self_id = settings.qq_self_id.strip()
        self._ws = None
        self._stop = asyncio.Event()
        self._send_lock = asyncio.Lock()
        self._echo = 0
        self._send_delay = 0.6

    def _connect_url(self) -> str:
        if not self.token:
            return self.url
        sep = "&" if "?" in self.url else "?"
        return f"{self.url}{sep}access_token={self.token}"

    async def open(self) -> None:
        if not self.url:
            raise RuntimeError("QQ_WS_URL 未配置")
        if not self.allowed:
            raise RuntimeError("QQ_ALLOWED_USERS 为空；私聊模式必须配置白名单")

    async def start(
        self, on_message: Callable[[ChannelMessage], Awaitable[None]]
    ) -> None:
        backoff = 1.0
        while not self._stop.is_set():
            try:
                async with connect(
                    self._connect_url(),
                    max_size=2**24,
                    ping_interval=20,
                    ping_timeout=20,
                ) as ws:
                    self._ws = ws
                    backoff = 1.0
                    log.info("QQ 已连接：%s", self.url)
                    async for raw in ws:
                        if self._stop.is_set():
                            break
                        try:
                            event = json.loads(raw)
                        except json.JSONDecodeError:
                            continue
                        msg = self._to_message(event)
                        if msg is None:
                            continue
                        try:
                            await on_message(msg)
                        except StopCompanion:
                            raise
                        except Exception:
                            log.exception("处理 QQ 消息失败")
            except StopCompanion:
                raise
            except (ConnectionClosed, OSError):
                if self._stop.is_set():
                    break
                log.warning("QQ 连接断开，%ss 后重连", int(backoff))
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)
            except Exception:
                if self._stop.is_set():
                    break
                log.exception("QQ 通道异常，%ss 后重连", int(backoff))
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)
            finally:
                self._ws = None
        raise StopCompanion

    def _to_message(self, event: dict[str, Any]) -> ChannelMessage | None:
        if event.get("post_type") != "message":
            return None
        if event.get("message_type") != "private":
            return None
        user_id = str(event.get("user_id", "")).strip()
        if not user_id:
            return None
        if self.self_id and user_id == self.self_id:
            return None
        if user_id not in self.allowed:
            return None
        text = extract_text(event)
        if not text:
            return None
        sender = event.get("sender") or {}
        name = sender.get("nickname") or sender.get("card") or None
        return ChannelMessage(
            channel="qq", user_id=user_id, text=text, display_name=name
        )

    async def send(self, to: str, text: str) -> None:
        if self._ws is None:
            raise RuntimeError("QQ 未连接")
        for chunk in split_message(text):
            self._echo += 1
            payload = build_send_payload(to, chunk, f"luo-{self._echo}")
            async with self._send_lock:
                await self._ws.send(json.dumps(payload, ensure_ascii=False))
            await asyncio.sleep(self._send_delay)

    async def stop(self) -> None:
        self._stop.set()
        ws = self._ws
        self._ws = None
        if ws is not None:
            try:
                await ws.close()
            except Exception:  # noqa: BLE001
                pass
