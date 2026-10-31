import asyncio

from luo.config import Settings
from luo.game.minecraft import (
    MinecraftChannel,
    parse_mc_intent,
    split_say,
)
from luo.runtime import map_session_key


class FakeMC(MinecraftChannel):
    def __init__(self):
        super().__init__(Settings(_env_file=None))
        self.calls = []

    async def call(self, skill, args):
        self.calls.append((skill, args))
        return {
            "spawned": True,
            "position": {"x": 1, "y": 2, "z": 3},
            "health": 20,
            "food": 20,
            "players": ["u"],
            "inventory": [],
        }


def test_mc_session_shares_local():
    assert map_session_key("mc", "local", {}) == "local"


def test_mc_tools():
    channel = FakeMC()
    names = {item["function"]["name"] for item in channel.game_tools()}
    assert names == {"mc_follow", "mc_stop", "mc_goto", "mc_state"}


def test_mc_state():
    channel = FakeMC()
    text = asyncio.run(channel.execute_skill("mc_state", {}))
    assert "1.0" in text
    assert "20" in text
    assert channel.calls == [("state", {})]


def test_mc_follow_defaults_to_last_speaker():
    channel = FakeMC()
    channel._last_speaker = "u"

    text = asyncio.run(channel.execute_skill("mc_follow", {}))

    assert "u" in text
    assert ("follow", {"player": "u"}) in channel.calls


def test_parse_mc_intent():
    assert parse_mc_intent("u: 洛，跟着我", "u") == (
        "mc_follow",
        {"player": "u"},
    )
    assert parse_mc_intent("u: 停下", "u") == ("mc_stop", {})
    assert parse_mc_intent("u: 你在哪", "u") == ("mc_state", {})
    assert parse_mc_intent("u: 今天天气不错", "u") is None
    assert parse_mc_intent("u: 别跟着我", "u") == ("mc_stop", {})


def test_split_say():
    assert split_say("短") == ["短"]
    chunks = split_say("啊" * 400)
    assert all(len(chunk) <= 180 for chunk in chunks)
