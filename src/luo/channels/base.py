from __future__ import annotations

from collections.abc import Awaitable, Callable

from ..core.interfaces import ChannelMessage


class StopCompanion(Exception):
    """收到 /quit 时抛出，用来结束通道循环。"""


class BaseChannel:
    """通道基类。

    默认行为是按用户缓冲整条回复，在 end_message 时一次性发送；终端通道
    覆盖 start_message / send_delta / end_message 来获得流式效果。
    """

    name = "base"

    def __init__(self) -> None:
        self._buffers: dict[str, list[str]] = {}

    async def open(self) -> None:
        pass

    async def send(self, to: str, text: str) -> None:
        raise NotImplementedError

    async def start_message(self, to: str) -> None:
        self._buffers[to] = []

    async def send_delta(self, to: str, text: str) -> None:
        self._buffers.setdefault(to, []).append(text)

    async def end_message(self, to: str) -> None:
        text = "".join(self._buffers.pop(to, [])).strip()
        if text:
            await self.send(to, text)

    async def start(
        self, on_message: Callable[[ChannelMessage], Awaitable[None]]
    ) -> None:
        raise NotImplementedError

    async def stop(self) -> None:
        pass
