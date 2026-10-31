import asyncio

from luo.config import Settings
from luo.game.minecraft import (
    MinecraftChannel,
    format_mc_event,
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
        if skill == "inventory":
            return {
                "items": [{"name": "木头", "count": 7}],
                "total": 1,
            }
        return {
            "spawned": True,
            "position": {"x": 1, "y": 2, "z": 3},
            "health": 20,
            "food": 20,
            "players": ["u"],
            "inventory": [{"name": "木头", "count": 3}],
        }


def test_mc_session_shares_local():
    assert map_session_key("mc", "local", {}) == "local"


def test_mc_tools():
    channel = FakeMC()
    names = {item["function"]["name"] for item in channel.game_tools()}
    assert names == {
        "mc_follow",
        "mc_stop",
        "mc_goto",
        "mc_state",
        "mc_inventory",
        "mc_collect",
        "mc_give",
    }


def test_mc_state():
    channel = FakeMC()
    text = asyncio.run(channel.execute_skill("mc_state", {}))
    assert "1.0" in text
    assert "20" in text
    assert "木头x3" in text
    assert channel.calls == [("state", {})]


def test_mc_inventory():
    channel = FakeMC()
    text = asyncio.run(channel.execute_skill("mc_inventory", {}))
    assert "木头x7" in text
    assert channel.calls == [("inventory", {})]


def test_mc_collect_and_give():
    channel = FakeMC()
    channel._last_speaker = "u"

    collect = asyncio.run(
        channel.execute_skill("mc_collect", {"block": "木头", "count": 3})
    )
    give = asyncio.run(
        channel.execute_skill("mc_give", {"item": "木头", "count": 2})
    )

    assert "木头" in collect
    assert "u" in give
    assert ("collect", {"block": "木头", "count": 3}) in channel.calls
    assert (
        "give",
        {"player": "u", "item": "木头", "count": 2},
    ) in channel.calls


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
    assert parse_mc_intent("u: 挖点木头", "u") == (
        "mc_collect",
        {"block": "木头", "count": 4},
    )
    assert parse_mc_intent("u: 挖八块石头", "u") == (
        "mc_collect",
        {"block": "石头", "count": 8},
    )
    assert parse_mc_intent("u: 你背包里有什么", "u") == (
        "mc_inventory",
        {},
    )
    assert parse_mc_intent("u: 给我点木头", "u") == (
        "mc_give",
        {"item": "木头", "count": 1, "player": "u"},
    )
    assert parse_mc_intent("u: 别挖了", "u") == ("mc_stop", {})
    assert parse_mc_intent("u: 帮我挖点木头", "u") == (
        "mc_collect",
        {"block": "木头", "count": 4},
    )
    assert parse_mc_intent("u: 洛，跟我来", "u") == (
        "mc_follow",
        {"player": "u"},
    )
    assert parse_mc_intent("u: 洛，过来", "u") == (
        "mc_follow",
        {"player": "u"},
    )
    # 闲聊不能误判成指令
    assert (
        parse_mc_intent("u: 洛，今天挖了木头，够不够搭个小房子", "u")
        is None
    )
    assert parse_mc_intent("u: 跟我讲个故事", "u") is None
    assert parse_mc_intent("u: 他给了我木头", "u") is None
    assert parse_mc_intent("u: 去挖了点木头", "u") is None


def test_format_mc_event():
    assert format_mc_event("death", {}) == (
        "event",
        "（游戏事件）洛在游戏里死了。",
    )
    assert format_mc_event("player_joined", {"username": "u"}) == (
        "event",
        "（游戏事件）u 进入了服务器。",
    )
    assert format_mc_event("action_done", {"summary": "挖到了 木头x3。"}) == (
        "action",
        "挖到了 木头x3。",
    )
    assert format_mc_event("action_failed", {"error": "附近没找到木头"}) == (
        "action",
        "没干成：附近没找到木头。",
    )
    assert format_mc_event("unknown", {}) is None


def test_split_say():
    assert split_say("短") == ["短"]
    chunks = split_say("啊" * 400)
    assert all(len(chunk) <= 180 for chunk in chunks)
