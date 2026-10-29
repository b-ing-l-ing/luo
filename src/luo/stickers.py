from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

LIST_STICKERS_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "list_stickers",
        "description": (
            "列出机器人小号 QQ 的收藏表情（不是本地 memes/ 梗图库）。"
            "会先同步一次；query 可按备注/id 过滤。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "关键词，可选"},
                "limit": {"type": "integer", "description": "最多返回几条"},
            },
            "required": [],
        },
    },
}

SEND_STICKER_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "send_sticker",
        "description": (
            "从 QQ 收藏表情里挑一张发出去。ref 用 list_stickers 返回的 id "
            "或描述关键词。表情单独一条消息，不要和文字混在同一个气泡。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "ref": {"type": "string", "description": "表情 id、md5 或描述关键词"},
            },
            "required": ["ref"],
        },
    },
}

ANNOTATE_STICKERS_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "annotate_stickers",
        "description": (
            "给还没有备注的 QQ 收藏表情看图补描述和标签，之后就能按描述选表情。"
            "一次整理少量即可，不要反复调用。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "count": {"type": "integer", "description": "最多整理几个，默认 3"},
            },
            "required": [],
        },
    },
}


def parse_annotation(raw: str) -> tuple[str, list[str]]:
    data: Any = None
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        match = re.search(r"\{.*\}", str(raw or ""), re.S)
        if match:
            try:
                data = json.loads(match.group(0))
            except json.JSONDecodeError:
                data = None
    if not isinstance(data, dict):
        return "", []
    note = str(data.get("note") or "").strip()[:200]
    tags = [
        str(tag).strip()[:20]
        for tag in (data.get("tags") or [])
        if str(tag).strip()
    ][:6]
    return note, tags


@dataclass
class Sticker:
    id: str
    url: str
    md5: str = ""
    desc: str = ""
    note: str = ""
    tags: list[str] = field(default_factory=list)
    use_count: int = 0
    last_used: float = 0.0

    def label(self) -> str:
        text = self.desc or self.note or "（无备注，可看图标）"
        tags = "、".join(self.tags) if self.tags else ""
        extra = f" [{tags}]" if tags else ""
        used = f"（用过{self.use_count}次）" if self.use_count else ""
        return f"[{self.id}] {text}{extra}{used}"


class StickerLibrary:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.entries: list[Sticker] = []
        self.load()

    def load(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(raw, list):
            return
        for item in raw:
            if not isinstance(item, dict):
                continue
            sticker_id = str(item.get("id") or "").strip()
            url = str(item.get("url") or "").strip()
            if not sticker_id or not url:
                continue
            try:
                use_count = max(0, int(item.get("use_count") or 0))
            except (TypeError, ValueError):
                use_count = 0
            try:
                last_used = float(item.get("last_used") or 0.0)
            except (TypeError, ValueError):
                last_used = 0.0
            self.entries.append(
                Sticker(
                    id=sticker_id,
                    url=url,
                    md5=str(item.get("md5") or "").strip().upper(),
                    desc=str(item.get("desc") or "").strip()[:200],
                    note=str(item.get("note") or "").strip()[:200],
                    tags=[
                        str(tag).strip()[:20]
                        for tag in (item.get("tags") or [])
                        if str(tag).strip()
                    ][:10],
                    use_count=use_count,
                    last_used=last_used,
                )
            )

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(
                [asdict(entry) for entry in self.entries],
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    def merge(self, fetched: list[dict[str, Any]]) -> int:
        added = 0
        changed = False
        by_id = {entry.id: entry for entry in self.entries}
        for item in fetched:
            if not isinstance(item, dict):
                continue
            sticker_id = str(
                item.get("emoji_id") or item.get("resId") or item.get("id") or ""
            ).strip()
            url = str(item.get("url") or "").strip()
            if not sticker_id or not url:
                continue
            desc = str(item.get("desc") or "").strip()[:200]
            md5 = str(item.get("md5") or "").strip().upper()
            old = by_id.get(sticker_id)
            if old is None:
                entry = Sticker(id=sticker_id, url=url, md5=md5, desc=desc)
                self.entries.append(entry)
                by_id[sticker_id] = entry
                added += 1
                changed = True
            else:
                if url and old.url != url:
                    old.url = url
                    changed = True
                if md5 and old.md5 != md5:
                    old.md5 = md5
                    changed = True
                if desc and old.desc != desc:
                    old.desc = desc
                    changed = True
        if changed:
            self.save()
        return added

    def list(self, query: str = "", limit: int = 20) -> list[Sticker]:
        text = str(query or "").strip().lower()
        entries = [
            entry
            for entry in self.entries
            if not text
            or text in " ".join(
                [
                    entry.desc,
                    entry.note,
                    entry.id,
                    entry.md5,
                    *entry.tags,
                ]
            ).lower()
        ]
        entries.sort(
            key=lambda entry: (entry.use_count, bool(entry.desc or entry.note)),
            reverse=True,
        )
        return entries[: max(1, min(int(limit or 20), 100))]

    def find(self, ref: str) -> Sticker | None:
        raw = str(ref or "").strip()
        if not raw:
            return None
        upper = raw.upper()
        for entry in self.entries:
            if entry.id == raw or (entry.md5 and entry.md5 == upper):
                return entry
        for entry in self.entries:
            haystack = " ".join(
                [entry.desc, entry.note, *entry.tags]
            ).lower()
            if raw.lower() in haystack:
                return entry
        return None

    def missing_note(self, limit: int = 3) -> list[Sticker]:
        entries = [
            entry
            for entry in self.entries
            if not entry.desc and not entry.note
        ]
        return entries[: max(1, min(int(limit or 3), 10))]

    def set_note(self, entry: Sticker, note: str, tags: list[str]) -> None:
        entry.note = str(note or "").strip()[:200]
        entry.tags = [
            str(tag).strip()[:20] for tag in tags if str(tag).strip()
        ][:10]
        self.save()

    def mark_used(self, entry: Sticker) -> None:
        entry.use_count += 1
        entry.last_used = time.time()
        self.save()
