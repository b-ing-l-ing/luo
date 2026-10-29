from luo.stickers import StickerLibrary, parse_annotation


def test_sticker_library_merge_find_and_persist(tmp_path):
    path = tmp_path / "stickers.json"
    library = StickerLibrary(path)

    added = library.merge(
        [
            {
                "emoji_id": "1",
                "url": "https://example.com/a.png",
                "md5": "abc",
                "desc": "无语",
            },
            {
                "emoji_id": "2",
                "url": "https://example.com/b.gif",
                "desc": "笑死",
            },
        ]
    )

    assert added == 2
    assert library.find("无语").id == "1"
    assert library.find("abc").id == "1"
    assert [entry.id for entry in library.list("笑")] == ["2"]

    library.set_note(library.find("1"), "无语", ["无语", "无语子"])
    assert library.find("无语子").id == "1"

    library.mark_used(library.find("2"))
    assert library.find("2").use_count == 1

    reloaded = StickerLibrary(path)
    assert len(reloaded.entries) == 2
    assert reloaded.find("2").use_count == 1
    assert reloaded.find("无语子").note == "无语"


def test_parse_annotation():
    note, tags = parse_annotation(
        '{"note":"无语","tags":["无语","无语子"]}'
    )
    assert note == "无语"
    assert tags == ["无语", "无语子"]
    assert parse_annotation("not json") == ("", [])
