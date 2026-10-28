"""启动时的主动开口。

只在有上次摘要或未完成的事时使用；第一次启动保持安静，避免硬找话说。
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Protocol

from .llm import Message
from .store import Store

GREETING_PROMPT = """用户刚打开对话，还没说话。你先开口，最多 25 个字，1 句话。
如果有没做完的事，自然地提一句；否则顺着上次聊到的内容说一句。
不要打招呼式客套，不要问“有什么可以帮你”，不要总结，不要说“根据记忆/记录”。
只输出你要说的那句话。"""


class SupportsStream(Protocol):
    def stream(self, messages: list[Message]) -> Iterator[str]: ...


def build_greeting_messages(
    persona: str, open_loops: list[str]
) -> list[Message]:
    system = persona
    if open_loops:
        items = "\n".join(f"- {item}" for item in open_loops[:5])
        system = f"{system}\n\n【还没做完的事】\n{items}"
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": GREETING_PROMPT},
    ]


def greet(
    llm: SupportsStream,
    store: Store,
    persona: str,
    open_loops: list[str],
    *,
    emit: Callable[[str], None] = print,
    session_id: str = "local",
) -> str:
    messages = build_greeting_messages(persona, open_loops)
    parts: list[str] = []
    for delta in llm.stream(messages):
        parts.append(delta)
        emit(delta)
    text = "".join(parts).strip()
    if text:
        store.add_event(session_id, "assistant", text)
    return text
