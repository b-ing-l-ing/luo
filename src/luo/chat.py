from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any, Protocol

from .llm import Message
from .memory import MemoryManager
from .store import Store

SESSION_ID = "local"


class SupportsStream(Protocol):
    def stream(self, messages: list[Message]) -> Iterator[str]: ...


def load_persona(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(f"找不到人设文件：{path}")
    return path.read_text(encoding="utf-8").strip()


def build_messages(
    persona: str,
    memory_block: str,
    history: list[Message],
    user_text: str,
    images: tuple[str, ...] = (),
) -> list[Message]:
    system = persona
    if memory_block:
        system = f"{system}\n\n{memory_block}"
    if images:
        user_content: Any = [
            {"type": "text", "text": user_text or "（图片）"},
            *[
                {"type": "image_url", "image_url": {"url": url}}
                for url in images
            ],
        ]
    else:
        user_content = user_text
    return [
        {"role": "system", "content": system},
        *history,
        {"role": "user", "content": user_content},
    ]


def respond(
    llm: SupportsStream,
    store: Store,
    persona: str,
    history: list[Message],
    user_text: str,
    *,
    memory: MemoryManager | None = None,
    emit: Callable[[str], None] = print,
    history_limit: int = 20,
    session_id: str = SESSION_ID,
    images: tuple[str, ...] = (),
) -> str:
    store.add_event(session_id, "user", user_text)
    memory_block = memory.render_for(user_text) if memory else ""
    messages = build_messages(
        persona, memory_block, history, user_text, images
    )

    parts: list[str] = []
    for delta in llm.stream(messages):
        parts.append(delta)
        emit(delta)

    reply = "".join(parts).strip()
    if reply:
        store.add_event(session_id, "assistant", reply)
        history.append({"role": "user", "content": user_text})
        history.append({"role": "assistant", "content": reply})
        if history_limit > 0 and len(history) > history_limit:
            del history[:-history_limit]
    return reply
