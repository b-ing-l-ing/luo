import asyncio
import base64

from luo.channels.base import BaseChannel, StopCompanion
from luo.config import Settings
from luo.core.interfaces import ChannelMessage
from luo.runtime import CompanionRuntime, map_session_key, parse_aliases
from luo.store import Store


class FakeChannel(BaseChannel):
    name = "fake"

    def __init__(self, inputs):
        super().__init__()
        self.inputs = inputs
        self.sent = []
        self.delta = []
        self.images = []
        self.faces = []

    async def start(self, on_message):
        for msg in self.inputs:
            await on_message(msg)
        raise StopCompanion

    async def send(self, to, text):
        self.sent.append((to, text))

    async def send_image(self, to, data, mime):
        self.images.append((to, data, mime))

    async def fetch_custom_faces(self, count=100):
        return self.faces

    async def start_message(self, to):
        self.delta = []

    async def send_delta(self, to, text):
        self.delta.append(text)

    async def end_message(self, to):
        text = "".join(self.delta).strip()
        self.delta = []
        if text:
            self.sent.append((to, text))


class FakeAsyncLLM:
    def __init__(self, chunks, reply=""):
        self.chunks = chunks
        self.reply = reply
        self.calls = []
        self.complete_calls = []

    async def stream(self, messages):
        self.calls.append(messages)
        for chunk in self.chunks:
            yield chunk

    async def stream_with_tools(self, messages, tools, execute_tool, *, max_rounds=3):
        async for chunk in self.stream(messages):
            yield chunk

    async def complete(self, messages, *, json_mode=False):
        self.complete_calls.append(messages)
        return self.reply


class FakeSyncLLM:
    def stream(self, messages):
        return iter(())

    def complete(self, messages, *, json_mode=False):
        return ""


def test_runtime_chat_turn(tmp_path):
    settings = Settings(_env_file=None, startup_greeting=False)
    db = tmp_path / "t.db"
    store = Store(db)
    channel = FakeChannel(
        [
            ChannelMessage("fake", "u", "hello"),
            ChannelMessage("fake", "u", "/quit"),
        ]
    )
    runtime = CompanionRuntime(
        settings,
        channel,
        store=store,
        sync_llm=FakeSyncLLM(),
        async_llm=FakeAsyncLLM(["hi", " there"]),
    )

    asyncio.run(runtime.run())

    assert ("u", "hi there") in channel.sent

    check = Store(db)
    assert check.recent_events("fake:u", 10) == [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi there"},
    ]
    check.close()


def test_runtime_sessions_are_isolated(tmp_path):
    settings = Settings(_env_file=None, startup_greeting=False)
    db = tmp_path / "t.db"
    store = Store(db)
    channel = FakeChannel(
        [
            ChannelMessage("fake", "a", "hello"),
            ChannelMessage("fake", "b", "yo"),
            ChannelMessage("fake", "a", "/quit"),
        ]
    )
    runtime = CompanionRuntime(
        settings,
        channel,
        store=store,
        sync_llm=FakeSyncLLM(),
        async_llm=FakeAsyncLLM(["ok"]),
    )

    asyncio.run(runtime.run())

    assert ("a", "ok") in channel.sent
    assert ("b", "ok") in channel.sent

    check = Store(db)
    assert [e["content"] for e in check.recent_events("fake:a", 10)] == [
        "hello",
        "ok",
    ]
    assert [e["content"] for e in check.recent_events("fake:b", 10)] == [
        "yo",
        "ok",
    ]
    check.close()


def test_session_aliases():
    aliases = parse_aliases("qq:123=me, local=me")
    assert map_session_key("qq", "123", aliases) == "me"
    assert map_session_key("terminal", "local", aliases) == "me"
    assert map_session_key("qq", "999", aliases) == "qq:999"


def test_runtime_alias_shares_session(tmp_path):
    settings = Settings(
        _env_file=None,
        startup_greeting=False,
        session_aliases="fake:a=shared",
    )
    db = tmp_path / "t.db"
    store = Store(db)
    channel = FakeChannel(
        [
            ChannelMessage("fake", "a", "hello"),
            ChannelMessage("fake", "a", "/quit"),
        ]
    )
    runtime = CompanionRuntime(
        settings,
        channel,
        store=store,
        sync_llm=FakeSyncLLM(),
        async_llm=FakeAsyncLLM(["ok"]),
    )

    asyncio.run(runtime.run())

    check = Store(db)
    assert [e["content"] for e in check.recent_events("shared", 10)] == [
        "hello",
        "ok",
    ]
    check.close()


def test_proactive_once(tmp_path):
    settings = Settings(
        _env_file=None,
        startup_greeting=False,
        proactive_idle_minutes=0,
        proactive_cooldown_minutes=60,
    )
    store = Store(tmp_path / "t.db")
    channel = FakeChannel([])
    async_llm = FakeAsyncLLM([], reply="上次说的末影龙还打吗？")
    runtime = CompanionRuntime(
        settings,
        channel,
        store=store,
        sync_llm=FakeSyncLLM(),
        async_llm=async_llm,
    )
    session = runtime._get_session("qq", "u")
    store.add_memory(
        session.key, "promise", "明天一起打末影龙", 4, status="open"
    )
    session.refresh_open_loops()
    session.last_activity = 0.0

    sent = asyncio.run(runtime.proactive_once())

    assert sent == [("u", "上次说的末影龙还打吗？")]
    assert ("u", "上次说的末影龙还打吗？") in channel.sent
    store.close()


def test_runtime_sticker_library(tmp_path, monkeypatch):
    settings = Settings(
        _env_file=None,
        startup_greeting=False,
        stickers_path=tmp_path / "stickers.json",
    )
    store = Store(tmp_path / "t.db")
    channel = FakeChannel([])
    channel.faces = [
        {
            "emoji_id": "1",
            "url": "https://example.com/a.png",
            "desc": "无语",
        }
    ]
    runtime = CompanionRuntime(
        settings,
        channel,
        store=store,
        sync_llm=FakeSyncLLM(),
        async_llm=FakeAsyncLLM([]),
    )

    listed = asyncio.run(
        runtime._execute_tool("list_stickers", "{}", to="u")
    )
    assert "无语" in listed

    data_url = "data:image/png;base64," + base64.b64encode(b"png").decode()
    monkeypatch.setattr(
        "luo.runtime.fetch_image_data_url", lambda url: data_url
    )
    sent = asyncio.run(
        runtime._execute_tool(
            "send_sticker", '{"ref":"无语"}', to="u"
        )
    )
    assert "已发送表情" in sent
    assert channel.images == [("u", b"png", "image/png")]
    store.close()


def test_runtime_annotates_stickers(tmp_path, monkeypatch):
    settings = Settings(
        _env_file=None,
        startup_greeting=False,
        stickers_path=tmp_path / "stickers.json",
    )
    store = Store(tmp_path / "t.db")
    channel = FakeChannel([])
    channel.faces = [
        {"emoji_id": "1", "url": "https://example.com/a.png", "desc": ""}
    ]
    data_url = "data:image/png;base64," + base64.b64encode(b"png").decode()
    monkeypatch.setattr(
        "luo.runtime.fetch_image_data_url", lambda url: data_url
    )
    runtime = CompanionRuntime(
        settings,
        channel,
        store=store,
        sync_llm=FakeSyncLLM(),
        async_llm=FakeAsyncLLM(
            [], reply='{"note":"无语","tags":["无语","无语子"]}'
        ),
    )

    result = asyncio.run(
        runtime._execute_tool(
            "annotate_stickers", '{"count":1}', to="u"
        )
    )
    assert "无语" in result
    assert runtime.stickers.find("无语子") is not None

    sent = asyncio.run(
        runtime._execute_tool(
            "send_sticker", '{"ref":"无语"}', to="u"
        )
    )
    assert "已发送表情" in sent
    assert channel.images
    store.close()


def test_runtime_send_meme(tmp_path):
    memes = tmp_path / "memes"
    memes.mkdir()
    (memes / "无语.png").write_bytes(b"png")

    settings = Settings(
        _env_file=None, startup_greeting=False, memes_dir=memes
    )
    store = Store(tmp_path / "t.db")
    channel = FakeChannel([])
    runtime = CompanionRuntime(
        settings,
        channel,
        store=store,
        sync_llm=FakeSyncLLM(),
        async_llm=FakeAsyncLLM([]),
    )

    result = asyncio.run(
        runtime._execute_tool("send_meme", '{"query":"无语"}', to="u")
    )

    assert "已发送" in result
    assert channel.images == [("u", b"png", "image/png")]
    store.close()


def test_runtime_saves_recent_image(tmp_path):
    memes = tmp_path / "memes"
    memes.mkdir()
    settings = Settings(
        _env_file=None, startup_greeting=False, memes_dir=memes
    )
    store = Store(tmp_path / "t.db")
    channel = FakeChannel([])
    runtime = CompanionRuntime(
        settings,
        channel,
        store=store,
        sync_llm=FakeSyncLLM(),
        async_llm=FakeAsyncLLM([]),
    )
    url = "data:image/png;base64," + base64.b64encode(b"png").decode()

    asyncio.run(
        runtime.on_message(ChannelMessage("fake", "u", "", images=(url,)))
    )
    asyncio.run(
        runtime.on_message(ChannelMessage("fake", "u", "存这张图"))
    )

    files = list(memes.glob("saved_*.png"))
    assert len(files) == 1
    assert files[0].read_bytes() == b"png"
    assert any("存好了" in text for _, text in channel.sent)
    store.close()


def test_runtime_help_command(tmp_path):
    settings = Settings(_env_file=None, startup_greeting=False)
    store = Store(tmp_path / "t.db")
    channel = FakeChannel(
        [
            ChannelMessage("fake", "u", "/help"),
            ChannelMessage("fake", "u", "/quit"),
        ]
    )
    runtime = CompanionRuntime(
        settings,
        channel,
        store=store,
        sync_llm=FakeSyncLLM(),
        async_llm=FakeAsyncLLM([]),
    )

    asyncio.run(runtime.run())

    assert any("/remember" in text for _, text in channel.sent)
