from __future__ import annotations

import asyncio
import base64
import json
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import replace
from typing import Any

from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

from ..config import Settings
from ..core.interfaces import ChannelMessage
from ..images import _host_is_public, fetch_image_data_url
from .base import BaseChannel, StopCompanion

log = logging.getLogger("luo.qq")


def parse_allowed(raw: str) -> set[str]:
    return {item.strip() for item in raw.split(",") if item.strip()}


def extract_image_urls(event: dict[str, Any]) -> list[str]:
    message = event.get("message")
    urls: list[str] = []
    if isinstance(message, list):
        for segment in message:
            if not isinstance(segment, dict) or segment.get("type") != "image":
                continue
            data = segment.get("data") or {}
            url = str(data.get("url") or "").strip()
            if url.startswith("http://") or url.startswith("https://"):
                urls.append(url)
    return urls


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


def split_burst(text: str, max_parts: int = 3) -> list[str]:
    text = text.strip()
    if not text:
        return []
    parts = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    if len(parts) <= 1:
        return [text]
    if len(parts) > max_parts:
        parts = parts[: max_parts - 1] + [
            "\n\n".join(parts[max_parts - 1 :])
        ]
    return parts


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
        self._pending: dict[str, asyncio.Future] = {}
        self._echo = 0
        self._send_delay = 0.6
        self._burst_max = settings.qq_burst_max
        self._burst_delay = settings.qq_burst_delay

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

    async def request(
        self, action: str, params: dict[str, Any], timeout: float = 20.0
    ) -> dict[str, Any]:
        if self._ws is None:
            raise RuntimeError("QQ 未连接")
        self._echo += 1
        echo = f"req-{self._echo}"
        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()
        self._pending[echo] = future
        payload = {"action": action, "params": params, "echo": echo}
        try:
            async with self._send_lock:
                await self._ws.send(
                    json.dumps(payload, ensure_ascii=False)
                )
            return await asyncio.wait_for(future, timeout)
        finally:
            self._pending.pop(echo, None)

    async def fetch_custom_faces(
        self, count: int = 100
    ) -> list[dict[str, Any]]:
        response = await self.request(
            "fetch_custom_face_detail",
            {"count": max(1, count)},
            timeout=20,
        )
        if response.get("status") != "ok" or response.get("retcode") != 0:
            raise RuntimeError(
                "fetch_custom_face_detail 失败："
                + str(response.get("wording") or response.get("retcode"))
            )
        data = response.get("data")
        return data if isinstance(data, list) else []

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
                        echo = (
                            event.get("echo")
                            if isinstance(event, dict)
                            else None
                        )
                        if echo and echo in self._pending:
                            future = self._pending.get(echo)
                            if future is not None and not future.done():
                                future.set_result(event)
                            continue
                        msg = await self._prepare_message(event)
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

    async def _prepare_message(
        self, event: dict[str, Any]
    ) -> ChannelMessage | None:
        msg = self._to_message(event)
        if msg is None or not msg.images:
            return msg
        data_urls = await asyncio.gather(
            *[asyncio.to_thread(fetch_image_data_url, url) for url in msg.images]
        )
        return replace(
            msg, images=tuple(url for url in data_urls if url)
        )

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
        images = extract_image_urls(event)
        if not text and not images:
            return None
        sender = event.get("sender") or {}
        name = sender.get("nickname") or sender.get("card") or None
        return ChannelMessage(
            channel="qq",
            user_id=user_id,
            text=text or "（图片）",
            display_name=name,
            images=tuple(images[:3]),
        )

    async def _send_segments(
        self, to: str, segments: list[dict[str, Any]]
    ) -> None:
        if self._ws is None:
            raise RuntimeError("QQ 未连接")
        self._echo += 1
        payload = {
            "action": "send_private_msg",
            "params": {"user_id": int(to), "message": segments},
            "echo": f"luo-{self._echo}",
        }
        async with self._send_lock:
            await self._ws.send(json.dumps(payload, ensure_ascii=False))
        await asyncio.sleep(self._send_delay)

    async def send(self, to: str, text: str) -> None:
        for chunk in split_message(text):
            await self._send_segments(
                to, [{"type": "text", "data": {"text": chunk}}]
            )

    async def send_image(self, to: str, data: bytes, mime: str) -> None:
        encoded = base64.b64encode(data).decode()
        await self._send_segments(
            to,
            [{"type": "image", "data": {"file": f"base64://{encoded}"}}],
        )

    async def end_message(self, to: str) -> None:
        text = "".join(self._buffers.pop(to, [])).strip()
        if not text:
            return
        parts = split_burst(text, self._burst_max)
        for index, part in enumerate(parts):
            await self.send(to, part)
            if index < len(parts) - 1:
                await asyncio.sleep(self._burst_delay)

    async def stop(self) -> None:
        self._stop.set()
        ws = self._ws
        self._ws = None
        if ws is not None:
            try:
                await ws.close()
            except Exception:  # noqa: BLE001
                pass
