from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from rich.console import Console

from ..core.interfaces import ChannelMessage
from .base import BaseChannel, StopCompanion


class TerminalChannel(BaseChannel):
    name = "terminal"

    def __init__(self, console: Console | None = None) -> None:
        super().__init__()
        self.console = console or Console()

    async def start(
        self, on_message: Callable[[ChannelMessage], Awaitable[None]]
    ) -> None:
        while True:
            try:
                text = await asyncio.to_thread(input, "你: ")
            except (EOFError, KeyboardInterrupt):
                raise StopCompanion from None
            await on_message(
                ChannelMessage(channel="terminal", user_id="local", text=text)
            )

    async def send(self, to: str, text: str) -> None:
        self.console.print(text, markup=False, highlight=False)

    async def start_message(self, to: str) -> None:
        self.console.print("[bold green]洛[/] ", end="")

    async def send_delta(self, to: str, text: str) -> None:
        self.console.print(text, end="", markup=False, highlight=False)

    async def end_message(self, to: str) -> None:
        self.console.print()
