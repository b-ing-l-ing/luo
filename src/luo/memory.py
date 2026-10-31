from __future__ import annotations

import difflib
import json
import re
from datetime import datetime, timezone
from typing import Any, Protocol

from .config import Settings
from .llm import Message
from .store import Store

ALLOWED_KINDS = {
    "shared_experience",
    "preference",
    "promise",
    "inside_joke",
    "conflict",
    "fact",
}

EXTRACT_PROMPT = """你是一个记忆整理器。阅读下面的对话，提取值得长期记住的内容。

只输出 JSON，格式：
{"memories":[{"kind":"shared_experience|preference|promise|inside_joke|conflict|fact","content":"一句具体的话","importance":1-5,"status":"open|closed","source_event_ids":[数字]}],"resolve_ids":[数字]}

规则：
- 只根据用户的消息提取事实；助手的话只用来理解上下文，不要把助手说过的内容当成事实来源。
- 标着“系统”的行是游戏里真实发生的事件（死亡、进出服、洛做了什么），可以作为共同经历记录，但 importance 不要给太高。
- 不要重复记录已知记忆，也不要换个说法重记。
- content 要具体（人名、物品、数字、地点、时间），不要写“用户喜欢游戏”这种空话。
- 最多 5 条；没有值得记的就输出 {"memories":[]}。
- source_event_ids 从对话每行开头的 [evt:ID] 里选，优先选用户消息。
- importance 4-5 只给长期重要的事（承诺、重要偏好、共同经历），1-2 给琐事。
- status：承诺、约定、约好要做但还没做的事用 open；事实、偏好、已经发生的经历用 closed。
- resolve_ids：如果对话表明某条 open 记忆已经完成、取消或不再需要，把它的 id 填进来；只能从“已知记忆”里列出的 open 记忆里选，不要编造。"""


class SupportsComplete(Protocol):
    def complete(self, messages: list[Message], *, json_mode: bool = False) -> str: ...


def _parse_json_object(text: str) -> dict[str, Any] | None:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _validate_memories(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind", "")).strip()
        content = str(item.get("content", "")).strip()
        if kind not in ALLOWED_KINDS or not content:
            continue
        try:
            importance = int(item.get("importance", 3))
        except (TypeError, ValueError):
            importance = 3
        importance = max(1, min(5, importance))
        status = str(item.get("status", "")).strip().lower()
        if status not in {"open", "closed"}:
            status = "open" if kind == "promise" else "closed"
        source_ids: list[int] = []
        for value in item.get("source_event_ids", []) or []:
            try:
                source_ids.append(int(value))
            except (TypeError, ValueError):
                continue
        out.append(
            {
                "kind": kind,
                "content": content[:300],
                "importance": importance,
                "status": status,
                "source_event_ids": source_ids[:20],
            }
        )
        if len(out) >= 5:
            break
    return out


def _validate_resolve_ids(raw: Any) -> list[int]:
    if not isinstance(raw, list):
        return []
    out: list[int] = []
    for value in raw:
        try:
            memory_id = int(value)
        except (TypeError, ValueError):
            continue
        if memory_id not in out:
            out.append(memory_id)
    return out[:20]


def parse_extraction_payload(text: str) -> dict[str, Any]:
    data = _parse_json_object(text) or {}
    return {
        "memories": _validate_memories(data.get("memories")),
        "resolve_ids": _validate_resolve_ids(data.get("resolve_ids")),
    }


def parse_extraction(text: str) -> list[dict[str, Any]]:
    return parse_extraction_payload(text)["memories"]


def format_transcript(
    events: list[dict[str, Any]], assistant_label: str = "你"
) -> str:
    lines = []
    for event in events:
        if event["role"] == "user":
            role = "用户"
        elif event["role"] == "system":
            role = "系统"
        else:
            role = assistant_label
        lines.append(f"[evt:{event['id']}] {role}: {event['content']}")
    return "\n".join(lines)


def extract_memories(
    llm: SupportsComplete,
    events: list[dict[str, Any]],
    existing: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if not events:
        return {"memories": [], "resolve_ids": []}
    system = EXTRACT_PROMPT
    known = [item for item in (existing or []) if item.get("content")]
    if known:
        lines = "\n".join(
            f"- [id:{item.get('id')}][{item.get('status', 'closed')}] {item['content']}"
            for item in known[:50]
        )
        system += f"\n\n已知记忆（不要重复，也不要换个说法重记）：\n{lines}"
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": format_transcript(events)},
    ]
    raw = llm.complete(messages, json_mode=True)
    return parse_extraction_payload(raw)


def _normalize(text: str) -> str:
    return re.sub(r"[\s\W_]+", "", text.lower(), flags=re.UNICODE)


def is_similar(a: str, b: str, threshold: float = 0.8) -> bool:
    """归一化后做粗粒度相似度判断，挡住“名字叫小林 / 名字是小林”这类改写。"""
    left, right = _normalize(a), _normalize(b)
    if not left or not right:
        return False
    if left == right:
        return True
    return difflib.SequenceMatcher(None, left, right).ratio() >= threshold


SUMMARY_PROMPT = """你是一个会话记录员。用 1-3 句话总结下面这段对话：
聊了什么、一起做了什么、有没有没做完的事。
只写对话里出现过的内容，不要编造，不要评价。"""


def summarize_session(
    llm: SupportsComplete, events: list[dict[str, Any]]
) -> str:
    if not events:
        return ""
    messages = [
        {"role": "system", "content": SUMMARY_PROMPT},
        {"role": "user", "content": format_transcript(events, assistant_label="助手")},
    ]
    return llm.complete(messages).strip()[:500]


def query_terms(text: str) -> list[str]:
    """把查询拆成中文二元/三元组和英文单词，供关键词打分使用。"""
    terms = [t.lower() for t in re.findall(r"[A-Za-z0-9_]+", text) if len(t) >= 2]
    for run in re.findall(r"[一-鿿]+", text):
        for size in (2, 3):
            terms.extend(run[i : i + size] for i in range(len(run) - size + 1))
    seen: list[str] = []
    for term in terms:
        if term not in seen:
            seen.append(term)
    return seen[:24]


def _age_days(ts: str, now: datetime) -> float:
    try:
        then = datetime.fromisoformat(ts)
    except (TypeError, ValueError):
        return 0.0
    if then.tzinfo is None:
        then = then.replace(tzinfo=timezone.utc)
    return max(0.0, (now - then).total_seconds() / 86400)


def score_memory(
    memory: dict[str, Any], terms: list[str], now: datetime | None = None
) -> float:
    now = now or datetime.now(timezone.utc)
    importance = float(memory.get("importance", 3))
    recency = 1.0 / (1.0 + _age_days(str(memory.get("ts", "")), now) / 14.0)
    content = str(memory.get("content", "")).lower()
    hits = sum(1 for term in terms if term and term in content)
    # 命中 1 个词就应该明显加分，命中 2 个基本封顶；否则重要度会把无关记忆顶上来。
    keyword = min(1.0, hits * 0.6) if terms else 0.0
    return importance * 0.5 + recency * 0.3 + keyword * 2.5


def _clip_line(content: Any, line_chars: int) -> str:
    text = str(content)
    if line_chars > 0 and len(text) > line_chars:
        return text[: line_chars - 1] + "…"
    return text


def render_memory_block(
    memories: list[dict[str, Any]],
    max_chars: int = 0,
    line_chars: int = 0,
) -> str:
    if not memories:
        return ""
    open_items = [item for item in memories if item.get("status") == "open"]
    closed_items = [item for item in memories if item.get("status") != "open"]
    lines: list[str] = []
    if open_items:
        lines.append("【还没做完的事】")
        for memory in open_items:
            date = str(memory.get("ts", ""))[:10]
            content = _clip_line(memory.get("content", ""), line_chars)
            lines.append(f"- {content}（{date}）")
    if closed_items:
        lines.append("【你记得的事】")
        for memory in closed_items:
            date = str(memory.get("ts", ""))[:10]
            content = _clip_line(memory.get("content", ""), line_chars)
            lines.append(
                f"- [{memory.get('kind')}|重要度{memory.get('importance')}|{date}] "
                f"{content}"
            )
    lines.append("只在自然相关时提起，不要为了展示记忆硬聊旧话题；没记录的事就说不记得。")
    text = "\n".join(lines)
    if max_chars > 0 and len(text) > max_chars:
        text = text[:max_chars].rsplit("\n", 1)[0]
        text += "\n（其余记忆省略）"
    return text


class MemoryManager:
    def __init__(
        self, store: Store, llm: SupportsComplete, settings: Settings, session_id: str
    ) -> None:
        self.store = store
        self.llm = llm
        self.settings = settings
        self.session_id = session_id
        self._last_event_id = store.last_event_id(session_id)
        self._turns = 0
        self.last_resolved: list[int] = []

    def retrieve(self, user_text: str) -> list[dict[str, Any]]:
        if self.settings.memory_top_k <= 0:
            return []
        memories = self.store.all_memories(self.session_id)
        if not memories:
            return []
        terms = query_terms(user_text)
        ranked = sorted(
            memories, key=lambda memory: score_memory(memory, terms), reverse=True
        )
        # 未完成的事总是优先注入，避免“答应过的事”被关键词打分挤掉。
        open_items = [item for item in memories if item.get("status") == "open"][:5]
        picked: list[dict[str, Any]] = []
        seen: set[int] = set()
        for memory in [*open_items, *ranked]:
            memory_id = int(memory["id"])
            if memory_id in seen:
                continue
            seen.add(memory_id)
            picked.append(memory)
            if len(picked) >= self.settings.memory_top_k:
                break
        if picked:
            self.store.touch_memories([int(memory["id"]) for memory in picked])
        return picked

    def render_for(self, user_text: str) -> str:
        return render_memory_block(
            self.retrieve(user_text),
            max_chars=self.settings.memory_block_chars,
            line_chars=self.settings.memory_line_chars,
        )

    def on_turn(self) -> None:
        self.last_resolved = []
        self._turns += 1
        if self._turns >= self.settings.memory_extract_every:
            self.flush()

    def flush(self) -> list[dict[str, Any]]:
        self.last_resolved = []
        events = self.store.events_after(self.session_id, self._last_event_id)
        if not events:
            self._turns = 0
            return []
        existing = self.store.all_memories(self.session_id, limit=500)
        result = extract_memories(self.llm, events, existing)
        open_ids = {
            int(item["id"]) for item in existing if item.get("status") == "open"
        }
        resolved: list[int] = []
        for memory_id in result["resolve_ids"]:
            if memory_id in open_ids and self.store.set_memory_status(memory_id, "closed"):
                resolved.append(memory_id)
        stored: list[dict[str, Any]] = []
        for memory in result["memories"]:
            if any(is_similar(memory["content"], item["content"]) for item in existing):
                continue
            memory_id = self.store.add_memory(
                self.session_id,
                memory["kind"],
                memory["content"],
                memory["importance"],
                memory["source_event_ids"],
                memory.get("status", "closed"),
            )
            stored.append({**memory, "id": memory_id})
            existing.append({**memory, "id": memory_id})
        self._last_event_id = int(events[-1]["id"])
        self._turns = 0
        self.last_resolved = resolved
        return stored
