from luo.style import find_violations


def test_find_violations_assistant_voice():
    labels = find_violations(
        "作为一个AI助手，有什么我可以帮你的吗？希望对你有所帮助。"
    )
    assert "自称AI" in labels
    assert "客服式提问" in labels
    assert "客服式结尾" in labels


def test_find_violations_structured_speech():
    labels = find_violations("首先，这个游戏不错；其次，它有点卡。总的来说，还行。")
    assert "作文结构" in labels
    assert "总结腔" in labels


def test_find_violations_clean_friend_talk():
    text = "这游戏还行，就是有点卡。你上次不是说想换个存档吗？"
    assert find_violations(text) == []
