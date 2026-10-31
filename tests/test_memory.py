from datetime import datetime, timedelta, timezone

from luo.config import Settings
from luo.memory import (
    MemoryManager,
    format_transcript,
    is_similar,
    parse_extraction,
    parse_extraction_payload,
    query_terms,
    render_memory_block,
    score_memory,
    summarize_session,
)
from luo.store import Store


def test_parse_extraction_valid():
    text = (
        '{"memories":[{"kind":"preference","content":"用户不吃香菜",'
        '"importance":4,"status":"open","source_event_ids":[1,"2"]}]}'
    )
    assert parse_extraction(text) == [
        {
            "kind": "preference",
            "content": "用户不吃香菜",
            "importance": 4,
            "status": "open",
            "source_event_ids": [1, 2],
        }
    ]


def test_parse_extraction_code_fence_and_bad_items():
    text = (
        '```json\n{"memories":['
        '{"kind":"nope","content":"x"},'
        '{"kind":"fact","content":"y","importance":99}'
        "]}\n```"
    )
    result = parse_extraction(text)
    assert len(result) == 1
    assert result[0]["importance"] == 5


def test_parse_extraction_invalid():
    assert parse_extraction("not json") == []
    assert parse_extraction('{"memories": "x"}') == []
    assert parse_extraction('{"memories": []}') == []


def test_parse_extraction_promise_defaults_open():
    result = parse_extraction(
        '{"memories":[{"kind":"promise","content":"明天一起挖矿"}]}'
    )
    assert result[0]["status"] == "open"
    assert result[0]["importance"] == 3


def test_parse_extraction_payload_resolve_ids():
    payload = parse_extraction_payload(
        '{"memories":[],"resolve_ids":[1,"2",2,"x",3]}'
    )
    assert payload["resolve_ids"] == [1, 2, 3]


def test_memory_manager_auto_resolves_promise(tmp_path):
    store = Store(tmp_path / "t.db")
    memory_id = store.add_memory(
        "local", "promise", "明天一起打末影龙", 3, status="open"
    )
    settings = Settings(_env_file=None)
    fake = FakeComplete(
        '{"memories":[],"resolve_ids":[%d]}' % memory_id
    )
    manager = MemoryManager(store, fake, settings, "local")
    store.add_event("local", "user", "末影龙打完了，搞定了")

    assert manager.flush() == []
    assert store.all_memories("local")[0]["status"] == "closed"
    assert manager.last_resolved == [memory_id]
    store.close()


def test_query_terms_chinese():
    terms = query_terms("上次我们挖矿的事")
    assert "挖矿" in terms
    assert "我们" in terms


def test_query_terms_english():
    terms = query_terms("Minecraft 里的 iron ore")
    assert "minecraft" in terms
    assert "iron" in terms


def test_score_prefers_important_and_keyword():
    now = datetime.now(timezone.utc)
    old_important = {
        "content": "一起挖矿",
        "importance": 5,
        "ts": (now - timedelta(days=30)).isoformat(),
    }
    new_trivial = {
        "content": "今天吃了面",
        "importance": 1,
        "ts": now.isoformat(),
    }
    terms = ["挖矿"]
    assert score_memory(old_important, terms, now) > score_memory(new_trivial, terms, now)


def test_score_prefers_keyword_match_over_unrelated_important():
    now = datetime.now(timezone.utc)
    relevant = {"content": "下周去成都吃火锅", "importance": 3, "ts": now.isoformat()}
    unrelated = {"content": "用户不吃香菜", "importance": 4, "ts": now.isoformat()}
    terms = ["成都", "火锅"]
    assert score_memory(relevant, terms, now) > score_memory(unrelated, terms, now)


def test_is_similar_dedupes_rewording():
    assert is_similar("用户的名字叫小林", "用户的名字是小林。")
    assert not is_similar("用户不吃香菜", "用户喜欢香菜")


def test_render_memory_block():
    block = render_memory_block(
        [
            {
                "kind": "fact",
                "content": "用户喜欢香菜",
                "importance": 3,
                "ts": "2026-10-27T00:00:00+00:00",
            }
        ]
    )
    assert "【你记得的事】" in block
    assert "2026-10-27" in block
    assert "用户喜欢香菜" in block


def test_render_open_loops_first():
    block = render_memory_block(
        [
            {
                "kind": "promise",
                "content": "明天一起打末影龙",
                "importance": 4,
                "status": "open",
                "ts": "2026-10-27T00:00:00+00:00",
            },
            {
                "kind": "fact",
                "content": "用户叫小林",
                "importance": 3,
                "status": "closed",
                "ts": "2026-10-27T00:00:00+00:00",
            },
        ]
    )
    assert block.index("【还没做完的事】") < block.index("【你记得的事】")
    assert "明天一起打末影龙" in block


class FakeComplete:
    def __init__(self, text: str):
        self.text = text
        self.calls = []

    def complete(self, messages, *, json_mode=False):
        self.calls.append(messages)
        return self.text


def test_summarize_session():
    fake = FakeComplete("  用户和洛约好明天打末影龙。  ")
    summary = summarize_session(
        fake, [{"id": 1, "role": "user", "content": "明天打末影龙"}]
    )
    assert summary == "用户和洛约好明天打末影龙。"


def test_format_transcript_assistant_label():
    text = format_transcript(
        [
            {"id": 1, "role": "user", "content": "a"},
            {"id": 2, "role": "assistant", "content": "b"},
        ],
        assistant_label="助手",
    )
    assert "用户: a" in text
    assert "助手: b" in text


def test_memory_manager_flush_and_dedupe(tmp_path):
    store = Store(tmp_path / "t.db")
    settings = Settings(_env_file=None)
    fake = FakeComplete(
        '{"memories":[{"kind":"fact","content":"用户叫小林",'
        '"importance":3,"source_event_ids":[1]}]}'
    )
    manager = MemoryManager(store, fake, settings, "local")

    store.add_event("local", "user", "我叫小林")
    first = manager.flush()
    assert len(first) == 1
    assert store.all_memories("local")[0]["content"] == "用户叫小林"

    # 换个说法再来一次，应该被判重
    store.add_event("local", "user", "我叫小林")
    assert manager.flush() == []
    assert len(store.all_memories("local")) == 1
    store.close()


def test_memory_manager_render_for(tmp_path):
    store = Store(tmp_path / "t.db")
    settings = Settings(_env_file=None)
    manager = MemoryManager(store, FakeComplete(""), settings, "local")
    store.add_memory("local", "fact", "用户叫小林", 3)

    block = manager.render_for("我叫什么名字")
    assert "用户叫小林" in block
    store.close()


def test_memory_manager_renders_open_loops_without_keyword(tmp_path):
    store = Store(tmp_path / "t.db")
    settings = Settings(_env_file=None)
    manager = MemoryManager(store, FakeComplete(""), settings, "local")
    store.add_memory("local", "promise", "明天一起打末影龙", 2, status="open")

    block = manager.render_for("今天天气怎么样")
    assert "明天一起打末影龙" in block
    assert "【还没做完的事】" in block
    store.close()


def test_render_memory_block_limits():
    memories = [
        {
            "content": "很长的记忆" * 40,
            "kind": "fact",
            "importance": 5,
            "status": "closed",
            "ts": "2026-10-01T00:00:00+00:00",
        }
    ]

    block = render_memory_block(memories, max_chars=80, line_chars=20)

    assert "…" in block
    assert "其余记忆省略" in block
    assert len(block) <= 80 + len("\n（其余记忆省略）")
