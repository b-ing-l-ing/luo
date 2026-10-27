import sqlite3

from luo.store import Store


def test_events_roundtrip(tmp_path):
    store = Store(tmp_path / "t.db")
    store.add_event("local", "user", "hi")
    store.add_event("local", "assistant", "hello")
    assert store.recent_events("local", 10) == [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ]
    store.close()


def test_recent_limit_and_order(tmp_path):
    store = Store(tmp_path / "t.db")
    for index in range(5):
        store.add_event("local", "user", str(index))
    assert [event["content"] for event in store.recent_events("local", 2)] == ["3", "4"]
    store.close()


def test_events_after(tmp_path):
    store = Store(tmp_path / "t.db")
    first = store.add_event("local", "user", "a")
    second = store.add_event("local", "user", "b")
    after = store.events_after("local", first)
    assert [event["id"] for event in after] == [second]
    store.close()


def test_memories_and_reset(tmp_path):
    store = Store(tmp_path / "t.db")
    memory_id = store.add_memory("local", "fact", "用户喜欢香菜", 3, [1, 2])
    rows = store.all_memories("local")
    assert rows[0]["id"] == memory_id
    assert rows[0]["source_event_ids"] == [1, 2]
    assert store.delete_memory(memory_id)

    store.add_memory("local", "fact", "x", 1)
    store.add_event("local", "user", "hi")
    store.add_session_summary("local", "2026-10-27T10:00:00+00:00", 1, "旧摘要")
    store.reset_session("local")
    assert store.all_memories("local") == []
    assert store.recent_events("local", 10) == []
    assert store.recent_session_summaries("local") == []
    store.close()


def test_session_summaries(tmp_path):
    store = Store(tmp_path / "t.db")
    store.add_session_summary(
        "local", "2026-10-27T10:00:00+00:00", 4, "第一次会话"
    )
    store.add_session_summary(
        "local", "2026-10-27T11:00:00+00:00", 2, "第二次会话"
    )
    rows = store.recent_session_summaries("local", 1)
    assert len(rows) == 1
    assert rows[0]["summary"] == "第二次会话"
    assert rows[0]["event_count"] == 2
    store.close()


def test_set_memory_status(tmp_path):
    store = Store(tmp_path / "t.db")
    memory_id = store.add_memory("local", "promise", "明天一起挖矿", 3, status="open")
    assert store.all_memories("local")[0]["status"] == "open"
    assert store.set_memory_status(memory_id, "closed")
    row = store.all_memories("local")[0]
    assert row["status"] == "closed"
    assert row["resolved_at"]
    store.close()


def test_migrates_old_schema(tmp_path):
    db = tmp_path / "old.db"
    con = sqlite3.connect(db)
    con.executescript(
        """
        CREATE TABLE events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            session_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL
        );
        CREATE TABLE memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            session_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            content TEXT NOT NULL,
            importance INTEGER NOT NULL,
            source_event_ids TEXT NOT NULL DEFAULT '[]',
            last_access TEXT
        );
        INSERT INTO memories (ts, session_id, kind, content, importance)
        VALUES ('2026-01-01T00:00:00+00:00', 'local', 'fact', '旧记忆', 3);
        """
    )
    con.commit()
    con.close()

    store = Store(db)
    assert store.all_memories("local")[0]["status"] == "closed"
    store.add_memory("local", "promise", "新承诺", 3, status="open")
    assert store.all_memories("local")[0]["status"] == "open"
    store.close()


def test_memory_content_exists(tmp_path):
    store = Store(tmp_path / "t.db")
    store.add_memory("local", "fact", "同样的内容", 3)
    assert store.memory_content_exists("local", "同样的内容")
    assert not store.memory_content_exists("local", "别的内容")
    store.close()
