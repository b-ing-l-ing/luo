import asyncio
import json

import pytest
from websockets.asyncio.server import serve

from luo.channels.base import StopCompanion
from luo.channels.qq import (
    QQChannel,
    _host_is_public,
    build_send_payload,
    extract_image_urls,
    extract_text,
    fetch_image_data_url,
    parse_allowed,
    split_burst,
    split_message,
)
from luo.config import Settings


def test_parse_allowed():
    assert parse_allowed("123, 456,,789 , ") == {"123", "456", "789"}


def test_extract_text_array():
    event = {
        "message": [
            {"type": "text", "data": {"text": "hi "}},
            {"type": "image", "data": {}},
            {"type": "text", "data": {"text": "there"}},
        ]
    }
    assert extract_text(event) == "hi [图片]there"


def test_extract_text_string_and_raw():
    assert extract_text({"message": "hello"}) == "hello"
    assert extract_text({"raw_message": "raw"}) == "raw"


def test_split_message():
    assert split_message("短消息") == ["短消息"]
    chunks = split_message("啊" * 900)
    assert len(chunks) > 1
    assert all(len(chunk) <= 400 for chunk in chunks)


def test_build_send_payload():
    payload = build_send_payload("123", "hello", "e1")
    assert payload["action"] == "send_private_msg"
    assert payload["params"]["user_id"] == 123
    assert payload["params"]["message"] == [
        {"type": "text", "data": {"text": "hello"}}
    ]
    assert payload["echo"] == "e1"


def test_to_message_filters():
    settings = Settings(_env_file=None, qq_allowed_users="123")
    channel = QQChannel(settings)
    base = {
        "post_type": "message",
        "message_type": "private",
        "user_id": 123,
        "message": [{"type": "text", "data": {"text": "hi"}}],
        "sender": {"nickname": "小林"},
    }

    msg = channel._to_message(base)
    assert msg is not None
    assert msg.user_id == "123"
    assert msg.text == "hi"
    assert msg.display_name == "小林"

    assert channel._to_message({**base, "user_id": 999}) is None
    assert channel._to_message({**base, "message_type": "group"}) is None
    assert channel._to_message({**base, "post_type": "notice"}) is None


def test_extract_image_urls():
    event = {
        "message": [
            {"type": "text", "data": {"text": "看"}},
            {"type": "image", "data": {"url": "https://example.com/a.png"}},
        ]
    }
    assert extract_image_urls(event) == ["https://example.com/a.png"]


def test_to_message_keeps_images():
    settings = Settings(_env_file=None, qq_allowed_users="123")
    channel = QQChannel(settings)
    event = {
        "post_type": "message",
        "message_type": "private",
        "user_id": 123,
        "message": [
            {"type": "image", "data": {"url": "https://example.com/a.png"}}
        ],
    }
    msg = channel._to_message(event)
    assert msg is not None
    assert msg.images == ("https://example.com/a.png",)
    assert msg.text == "[图片]"


def test_image_fetch_rejects_private_hosts():
    assert not _host_is_public("127.0.0.1")
    assert not _host_is_public("localhost")
    assert fetch_image_data_url("http://127.0.0.1/a.png") is None


def test_split_burst():
    assert split_burst("一句") == ["一句"]
    assert split_burst("第一段\n\n第二段") == ["第一段", "第二段"]
    parts = split_burst("1\n\n2\n\n3\n\n4", 3)
    assert len(parts) == 3
    assert parts[-1].startswith("3")


def test_send_image_payload():
    class FakeWS:
        def __init__(self):
            self.sent = []

        async def send(self, raw):
            self.sent.append(json.loads(raw))

    channel = QQChannel(Settings(_env_file=None, qq_allowed_users="123"))
    channel._ws = FakeWS()
    channel._send_delay = 0

    asyncio.run(channel.send_image("123", b"abc", "image/png"))

    payload = channel._ws.sent[0]
    assert payload["action"] == "send_private_msg"
    assert payload["params"]["message"][0]["type"] == "image"
    assert payload["params"]["message"][0]["data"]["file"].startswith("base64://")


def test_qq_channel_ws_roundtrip():
    async def run():
        received = []
        done = asyncio.Event()
        event = {
            "post_type": "message",
            "message_type": "private",
            "user_id": 123,
            "message": [{"type": "text", "data": {"text": "hi"}}],
        }

        async def handler(ws):
            await ws.send(json.dumps(event, ensure_ascii=False))
            raw = await ws.recv()
            received.append(json.loads(raw))
            done.set()

        async with serve(handler, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            settings = Settings(
                _env_file=None,
                qq_ws_url=f"ws://127.0.0.1:{port}",
                qq_allowed_users="123",
            )
            channel = QQChannel(settings)

            async def on_message(msg):
                await channel.send(msg.user_id, "收到了")

            task = asyncio.create_task(channel.start(on_message))
            await asyncio.wait_for(done.wait(), 5)
            await channel.stop()
            with pytest.raises(StopCompanion):
                await asyncio.wait_for(task, 5)

        assert received[0]["action"] == "send_private_msg"
        assert received[0]["params"]["user_id"] == 123
        assert received[0]["params"]["message"][0]["data"]["text"] == "收到了"

    asyncio.run(run())
