import base64

from luo.images import (
    image_dimensions,
    is_save_request,
    parse_data_url,
    save_data_url,
)


def test_is_save_request():
    assert is_save_request("存这张图") == ""
    assert is_save_request("存这张图 无语") == "无语"
    assert is_save_request("帮我保存这张图") == ""
    assert is_save_request("这张图好好笑") is None
    assert is_save_request("存图功能怎么用") is None


def test_save_data_url(tmp_path):
    data = b"png"
    url = "data:image/png;base64," + base64.b64encode(data).decode()

    path = save_data_url(url, tmp_path, "无语")

    assert path is not None
    assert path.name == "无语.png"
    assert path.read_bytes() == data


def test_parse_data_url_rejects_non_data_url():
    assert parse_data_url("http://example.com/a.png") is None


def test_image_dimensions_png():
    png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8"
        "/x8AAusB9Wl2nXQAAAAASUVORK5CYII="
    )
    assert image_dimensions(png) == (1, 1)
