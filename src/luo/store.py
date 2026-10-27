from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_session ON events(session_id, id);

CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    session_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    content TEXT NOT NULL,
    importance INTEGER NOT NULL,
    source_event_ids TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'closed',
    resolved_at TEXT,
    last_access TEXT
);
CREATE INDEX IF NOT EXISTS idx_memories_session ON memories(session_id, id);

CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    started_at TEXT NOT NULL,
    ended_at TEXT NOT NULL,
    event_count INTEGER NOT NULL,
    summary TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_session ON sessions(session_id, id);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        self._migrate()
        self._conn.commit()

    def _migrate(self) -> None:
        columns = {
            row["name"]
            for row in self._conn.execute("PRAGMA table_info(memories)").fetchall()
        }
        if "status" not in columns:
            self._conn.execute(
                "ALTER TABLE memories ADD COLUMN status TEXT NOT NULL DEFAULT 'closed'"
            )
        if "resolved_at" not in columns:
            self._conn.execute("ALTER TABLE memories ADD COLUMN resolved_at TEXT")

    def add_event(self, session_id: str, role: str, content: str) -> int:
        cur = self._conn.execute(
            "INSERT INTO events (ts, session_id, role, content) VALUES (?, ?, ?, ?)",
            (_now(), session_id, role, content),
        )
        self._conn.commit()
        return int(cur.lastrowid)

    def recent_events(self, session_id: str, limit: int) -> list[dict[str, str]]:
        rows = self._conn.execute(
            "SELECT role, content FROM events WHERE session_id = ? ORDER BY id DESC LIMIT ?",
            (session_id, limit),
        ).fetchall()
        return [{"role": row["role"], "content": row["content"]} for row in reversed(rows)]

    def events_after(
        self, session_id: str, after_id: int, limit: int = 40
    ) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT id, ts, role, content FROM events "
            "WHERE session_id = ? AND id > ? ORDER BY id LIMIT ?",
            (session_id, after_id, limit),
        ).fetchall()
        return [dict(row) for row in rows]

    def last_event_id(self, session_id: str) -> int:
        row = self._conn.execute(
            "SELECT COALESCE(MAX(id), 0) AS max_id FROM events WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        return int(row["max_id"])

    def add_session_summary(
        self, session_id: str, started_at: str, event_count: int, summary: str
    ) -> int:
        cur = self._conn.execute(
            "INSERT INTO sessions (session_id, started_at, ended_at, event_count, summary) "
            "VALUES (?, ?, ?, ?, ?)",
            (session_id, started_at, _now(), event_count, summary),
        )
        self._conn.commit()
        return int(cur.lastrowid)

    def recent_session_summaries(
        self, session_id: str, limit: int = 3
    ) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT id, session_id, started_at, ended_at, event_count, summary "
            "FROM sessions WHERE session_id = ? ORDER BY id DESC LIMIT ?",
            (session_id, limit),
        ).fetchall()
        return [dict(row) for row in rows]

    def add_memory(
        self,
        session_id: str,
        kind: str,
        content: str,
        importance: int,
        source_event_ids: list[int] | None = None,
        status: str = "closed",
    ) -> int:
        if status not in {"open", "closed"}:
            status = "closed"
        cur = self._conn.execute(
            "INSERT INTO memories "
            "(ts, session_id, kind, content, importance, source_event_ids, status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                _now(),
                session_id,
                kind,
                content,
                importance,
                json.dumps(source_event_ids or []),
                status,
            ),
        )
        self._conn.commit()
        return int(cur.lastrowid)

    def all_memories(self, session_id: str, limit: int = 500) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT id, ts, kind, content, importance, source_event_ids, "
            "status, resolved_at, last_access "
            "FROM memories WHERE session_id = ? ORDER BY id DESC LIMIT ?",
            (session_id, limit),
        ).fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["source_event_ids"] = json.loads(item["source_event_ids"] or "[]")
            out.append(item)
        return out

    def memory_content_exists(self, session_id: str, content: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM memories WHERE session_id = ? AND content = ? LIMIT 1",
            (session_id, content),
        ).fetchone()
        return row is not None

    def touch_memories(self, ids: list[int]) -> None:
        if not ids:
            return
        ts = _now()
        self._conn.executemany(
            "UPDATE memories SET last_access = ? WHERE id = ?",
            [(ts, memory_id) for memory_id in ids],
        )
        self._conn.commit()

    def set_memory_status(self, memory_id: int, status: str) -> bool:
        if status not in {"open", "closed"}:
            return False
        resolved_at = _now() if status == "closed" else None
        cur = self._conn.execute(
            "UPDATE memories SET status = ?, resolved_at = ? WHERE id = ?",
            (status, resolved_at, memory_id),
        )
        self._conn.commit()
        return cur.rowcount > 0

    def delete_memory(self, memory_id: int) -> bool:
        cur = self._conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
        self._conn.commit()
        return cur.rowcount > 0

    def reset_session(self, session_id: str) -> None:
        self._conn.execute("DELETE FROM events WHERE session_id = ?", (session_id,))
        self._conn.execute("DELETE FROM memories WHERE session_id = ?", (session_id,))
        self._conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()
