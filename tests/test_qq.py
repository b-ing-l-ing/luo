import asyncio
import json

import pytest
from websockets.asyncio.server import serve

from luo.channels.base import StopCompanion
from luo.channels.qq import (
    QQChannel,
    build_send_payload,
    extract_text,
    parse_allowed,
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
