from luo.chat import build_messages, respond
from luo.store import Store


class FakeLLM:
    def __init__(self, chunks):
        self.chunks = chunks
        self.calls = []

    def stream(self, messages):
        self.calls.append(messages)
        yield from self.chunks


def test_respond_streams_and_stores(tmp_path):
    store = Store(tmp_path / "t.db")
    llm = FakeLLM(["你", "好"])
    history = []
    emitted = []

    reply = respond(llm, store, "persona", history, "嗨", emit=emitted.append)

    assert reply == "你好"
    assert "".join(emitted) == "你好"
    assert history == [
        {"role": "user", "content": "嗨"},
        {"role": "assistant", "content": "你好"},
    ]
    assert store.recent_events("local", 10) == [
        {"role": "user", "content": "嗨"},
        {"role": "assistant", "content": "你好"},
    ]
    store.close()


def test_respond_respects_history_limit(tmp_path):
    store = Store(tmp_path / "t.db")
    llm = FakeLLM(["ok"])
    history = [
        {"role": "user", "content": "old"},
        {"role": "assistant", "content": "old reply"},
    ]

    respond(llm, store, "persona", history, "new", history_limit=2)

    assert history == [
        {"role": "user", "content": "new"},
        {"role": "assistant", "content": "ok"},
    ]
    store.close()


def test_build_messages_with_memory():
    history = [{"role": "user", "content": "a"}]
    messages = build_messages("persona", "memory", history, "b")
    assert messages[0] == {"role": "system", "content": "persona\n\nmemory"}
    assert messages[1] == {"role": "user", "content": "a"}
    assert messages[-1] == {"role": "user", "content": "b"}
