from luo.greeting import build_greeting_messages, greet
from luo.store import Store


class FakeLLM:
    def __init__(self, chunks):
        self.chunks = chunks
        self.messages = None

    def stream(self, messages):
        self.messages = messages
        yield from self.chunks


def test_build_greeting_includes_persona_and_loops():
    messages = build_greeting_messages("你是洛。", ["明天一起打末影龙"])
    assert messages[0]["role"] == "system"
    assert "你是洛。" in messages[0]["content"]
    assert "明天一起打末影龙" in messages[0]["content"]
    assert messages[1]["role"] == "user"
    assert "你先开口" in messages[1]["content"]


def test_greet_streams_and_stores(tmp_path):
    store = Store(tmp_path / "t.db")
    llm = FakeLLM(["上次说的", "末影龙还打吗？"])
    emitted = []

    text = greet(
        llm,
        store,
        "你是洛。",
        ["明天一起打末影龙"],
        emit=emitted.append,
    )

    assert text == "上次说的末影龙还打吗？"
    assert "".join(emitted) == text
    assert store.recent_events("local", 10) == [
        {"role": "assistant", "content": text}
    ]
    assert "还没做完的事" in llm.messages[0]["content"]
    store.close()
