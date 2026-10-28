from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Protocol

from rich.console import Console
from rich.markup import escape
from rich.prompt import Prompt

from ..config import Settings
from ..greeting import greet
from ..llm import ChatLLM, Message
from ..memory import MemoryManager, summarize_session
from ..store import Store
from ..style import find_violations

SESSION_ID = "local"

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


class SupportsStream(Protocol):
    def stream(self, messages: list[Message]) -> Iterator[str]: ...


def load_persona(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(f"找不到人设文件：{path}")
    return path.read_text(encoding="utf-8").strip()


def build_messages(
    persona: str, memory_block: str, history: list[Message], user_text: str
) -> list[Message]:
    system = persona
    if memory_block:
        system = f"{system}\n\n{memory_block}"
    return [{"role": "system", "content": system}, *history, {"role": "user", "content": user_text}]


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
) -> str:
    store.add_event(session_id, "user", user_text)
    memory_block = memory.render_for(user_text) if memory else ""
    messages = build_messages(persona, memory_block, history, user_text)

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


def run(settings: Settings) -> None:
    console = Console()
    persona = load_persona(settings.persona_path)
    llm = ChatLLM(settings)
    store = Store(settings.db_path)
    last_summaries = store.recent_session_summaries(SESSION_ID, 1)
    if last_summaries:
        persona = f"{persona}\n\n【上次你们聊到】\n{last_summaries[0]['summary']}"
    session_start_event_id = store.last_event_id(SESSION_ID)
    history = store.recent_events(SESSION_ID, settings.history_limit)
    memory = MemoryManager(store, llm, settings, SESSION_ID)
    open_loops = [
        str(item["content"]) for item in store.open_memories(SESSION_ID, limit=5)
    ]

    console.print("[bold]洛 v0.3[/]  /help 查看命令")
    if history:
        console.print(f"[dim]已载入最近 {len(history)} 条消息[/]")
    if last_summaries:
        console.print("[dim]已载入上次会话摘要[/]")

    if settings.startup_greeting and (last_summaries or open_loops):
        console.print("[bold green]洛[/] ", end="")
        try:
            greeting = greet(
                llm,
                store,
                persona,
                open_loops,
                emit=lambda text: console.print(text, end="", markup=False, highlight=False),
                session_id=SESSION_ID,
            )
            if greeting:
                history.append({"role": "assistant", "content": greeting})
                if settings.style_debug:
                    hits = find_violations(greeting)
                    if hits:
                        console.print(f"\n[dim]AI味：{'、'.join(hits)}[/]")
        except Exception as exc:  # noqa: BLE001
            console.print(f"\n[dim]主动开口失败：{exc}[/]")
        console.print()

    try:
        while True:
            try:
                user_text = Prompt.ask("[bold cyan]你[/]")
            except (EOFError, KeyboardInterrupt):
                console.print()
                break

            user_text = user_text.strip()
            if not user_text:
                continue

            if user_text in {"/quit", "/exit"}:
                break
            if user_text == "/reset":
                store.reset_session(SESSION_ID)
                history.clear()
                persona = load_persona(settings.persona_path)
                session_start_event_id = 0
                memory = MemoryManager(store, llm, settings, SESSION_ID)
                console.print("[yellow]已清空本会话的事件、记忆和摘要[/]")
                continue
            if user_text == "/memory":
                rows = store.all_memories(SESSION_ID, limit=100)
                if not rows:
                    console.print("[dim]还没有记忆[/]")
                for row in rows:
                    state = "未完成" if row["status"] == "open" else "已归档"
                    console.print(
                        f"[dim]{row['id']}.[/] ({row['kind']}|{state}) "
                        f"{escape(str(row['content']))} "
                        f"[dim]重要度{row['importance']} {str(row['ts'])[:10]}[/]"
                    )
                continue
            if user_text == "/help":
                console.print(HELP_TEXT, markup=False)
                continue
            if user_text == "/summary":
                rows = store.recent_session_summaries(SESSION_ID, 3)
                if not rows:
                    console.print("[dim]还没有会话摘要[/]")
                for row in rows:
                    console.print(
                        f"[dim]{str(row['ended_at'])[:16]}[/] "
                        f"{escape(str(row['summary']))}"
                    )
                continue
            if user_text.startswith("/remember "):
                content = user_text[len("/remember ") :].strip()
                if not content:
                    console.print("[yellow]用法：/remember <内容>[/]")
                    continue
                store.add_memory(SESSION_ID, "fact", content[:300], 4, status="closed")
                console.print("[green]已记住[/]")
                continue
            if user_text.startswith("/promise "):
                content = user_text[len("/promise ") :].strip()
                if not content:
                    console.print("[yellow]用法：/promise <内容>[/]")
                    continue
                store.add_memory(SESSION_ID, "promise", content[:300], 4, status="open")
                console.print("[green]已记下这件没做完的事[/]")
                continue
            if user_text.startswith("/done"):
                parts = user_text.split()
                if len(parts) != 2 or not parts[1].isdigit():
                    console.print("[yellow]用法：/done <id>，id 从 /memory 里看[/]")
                    continue
                done = store.set_memory_status(int(parts[1]), "closed")
                console.print("[green]已标记完成[/]" if done else "[yellow]没找到这条记忆[/]")
                continue
            if user_text.startswith("/forget"):
                parts = user_text.split()
                if len(parts) != 2 or not parts[1].isdigit():
                    console.print("[yellow]用法：/forget <id>，id 从 /memory 里看[/]")
                    continue
                deleted = store.delete_memory(int(parts[1]))
                console.print("[green]已删除[/]" if deleted else "[yellow]没找到这条记忆[/]")
                continue

            console.print("[bold green]洛[/] ", end="")
            try:
                reply = respond(
                    llm,
                    store,
                    persona,
                    history,
                    user_text,
                    memory=memory,
                    emit=lambda text: console.print(text, end="", markup=False, highlight=False),
                    history_limit=settings.history_limit,
                )
                if settings.style_debug:
                    hits = find_violations(reply)
                    if hits:
                        console.print(f"\n[dim]AI味：{'、'.join(hits)}[/]")
            except Exception as exc:  # noqa: BLE001 - 终端里给出可读错误即可
                console.print(f"\n[red]模型调用失败：{exc}[/]")
                continue
            console.print()

            try:
                memory.on_turn()
                if memory.last_resolved:
                    console.print(f"[dim]记忆整理：完成 {len(memory.last_resolved)} 条[/]")
            except Exception as exc:  # noqa: BLE001
                console.print(f"[dim]记忆抽取失败：{exc}[/]")
    finally:
        try:
            added = memory.flush()
            if added:
                console.print(f"[dim]记忆整理：新增 {len(added)} 条[/]")
            if memory.last_resolved:
                console.print(f"[dim]记忆整理：完成 {len(memory.last_resolved)} 条[/]")
        except Exception as exc:  # noqa: BLE001
            console.print(f"[yellow]记忆整理失败：{exc}[/]")

        try:
            events = store.events_after(SESSION_ID, session_start_event_id)
            if events:
                summary = summarize_session(llm, events)
                if summary:
                    store.add_session_summary(
                        SESSION_ID, str(events[0]["ts"]), len(events), summary
                    )
                    console.print("[dim]会话摘要：已保存[/]")
        except Exception as exc:  # noqa: BLE001
            console.print(f"[yellow]会话摘要失败：{exc}[/]")
        store.close()
