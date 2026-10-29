import os
import random
import time

from luo.memes import MemeLibrary


def test_meme_library(tmp_path):
    (tmp_path / "无语.png").write_bytes(b"x")
    (tmp_path / "笑死.jpg").write_bytes(b"y")
    (tmp_path / "notes.txt").write_text("x", encoding="utf-8")

    library = MemeLibrary(tmp_path)
    assert set(library.tags()) == {"无语", "笑死"}
    assert library.find("无语").name == "无语.png"
    assert library.find("不存在") is None
    assert library.mime_for(tmp_path / "无语.png") == "image/png"


def test_meme_library_detects_duplicate(tmp_path):
    (tmp_path / "a.png").write_bytes(b"same")
    library = MemeLibrary(tmp_path)
    assert library.has_same_content(b"same")
    assert not library.has_same_content(b"other")


def test_meme_library_prefers_newer_variants(tmp_path):
    old = tmp_path / "无语.png"
    new = tmp_path / "无语_2.png"
    old.write_bytes(b"old")
    new.write_bytes(b"new")
    now = time.time()
    os.utime(old, (now - 1000, now - 1000))
    os.utime(new, (now, now))

    library = MemeLibrary(tmp_path)
    rng = random.Random(0)
    picks = [library.find("无语", rng=rng) for _ in range(200)]

    assert picks.count(new) > picks.count(old)
