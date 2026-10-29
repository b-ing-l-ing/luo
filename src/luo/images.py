from __future__ import annotations

import base64
import ipaddress
import re
import socket
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

EXTENSIONS = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
}

SAVE_PHRASES = (
    "存这张图",
    "保存这张图",
    "收藏这张图",
    "保存一下这张图",
    "存一下这张图",
    "存一下图",
    "把这张图存",
    "这张图存",
    "存图",
)


def is_save_request(text: str) -> str | None:
    """识别“存这张图”类指令；返回标签（可能为空字符串），不是存图请求返回 None。"""
    text = str(text or "").strip()
    if not text or len(text) > 40:
        return None
    if any(word in text for word in ("怎么", "如何", "为什么", "?", "？")):
        return None
    stripped = re.sub(r"^(帮我|给我|麻烦|请)", "", text).strip()
    for phrase in SAVE_PHRASES:
        if stripped.startswith(phrase):
            return stripped[len(phrase) :].strip(" ，,。.!！:：")[:30]
    return None


def parse_data_url(url: str) -> tuple[bytes, str] | None:
    if not url.startswith("data:") or ";base64," not in url:
        return None
    header, payload = url.split(",", 1)
    mime = header[5:].split(";")[0].strip().lower()
    try:
        data = base64.b64decode(payload)
    except (ValueError, TypeError):
        return None
    return data, mime


def _safe_tag(tag: str) -> str:
    tag = re.sub(r"\s+", "_", tag)
    return re.sub(r'[\\/:*?"<>|\x00-\x1f]', "", tag).strip(" ._")[:40]


def image_dimensions(data: bytes) -> tuple[int, int] | None:
    """尽量从图片头里读宽高；读不出返回 None。"""
    if data.startswith(b"\x89PNG\r\n\x1a\n") and len(data) >= 24:
        return (
            int.from_bytes(data[16:20], "big"),
            int.from_bytes(data[20:24], "big"),
        )
    if data[:6] in (b"GIF87a", b"GIF89a") and len(data) >= 10:
        return (
            int.from_bytes(data[6:8], "little"),
            int.from_bytes(data[8:10], "little"),
        )
    if data.startswith(b"\xff\xd8"):
        index = 2
        while index + 9 < len(data):
            if data[index] != 0xFF:
                index += 1
                continue
            marker = data[index + 1]
            if marker in (0xD8, 0xD9, 0x01) or 0xD0 <= marker <= 0xD7:
                index += 2
                continue
            length = int.from_bytes(data[index + 2 : index + 4], "big")
            if length < 2:
                break
            if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
                height = int.from_bytes(data[index + 5 : index + 7], "big")
                width = int.from_bytes(data[index + 7 : index + 9], "big")
                return width, height
            index += 2 + length
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP" and len(data) >= 30:
        if data[12:16] == b"VP8X":
            width = 1 + int.from_bytes(data[24:27], "little")
            height = 1 + int.from_bytes(data[27:30], "little")
            return width, height
    return None


def _host_is_public(host: str) -> bool:
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return False
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            return False
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            return False
    return True


class _SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parsed = urllib.parse.urlparse(newurl)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or not _host_is_public(parsed.hostname)
        ):
            return None
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_OPENER = urllib.request.build_opener(_SafeRedirect())


def fetch_image_data_url(
    url: str, max_bytes: int = 8 * 1024 * 1024, timeout: float = 15.0
) -> str | None:
    """下载图片并转 data URL。只允许 http(s)、公网地址、image/*、8MB 以内。"""
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None
    if not _host_is_public(parsed.hostname):
        return None
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": "Mozilla/5.0"}
        )
        with _OPENER.open(req, timeout=timeout) as resp:
            final = urllib.parse.urlparse(resp.geturl())
            if not final.hostname or not _host_is_public(final.hostname):
                return None
            mime = resp.headers.get_content_type()
            if not mime.startswith("image/"):
                return None
            data = resp.read(max_bytes + 1)
            if len(data) > max_bytes:
                return None
        return f"data:{mime};base64,{base64.b64encode(data).decode()}"
    except Exception:  # noqa: BLE001
        return None


def save_data_url(url: str, root: Path, tag: str | None = None) -> Path | None:
    parsed = parse_data_url(url)
    if parsed is None:
        return None
    data, mime = parsed
    extension = EXTENSIONS.get(mime)
    if extension is None:
        return None
    root.mkdir(parents=True, exist_ok=True)
    name = _safe_tag(tag or "") or f"saved_{datetime.now():%Y%m%d_%H%M%S}"
    path = root / f"{name}{extension}"
    counter = 2
    while path.exists():
        path = root / f"{name}_{counter}{extension}"
        counter += 1
    try:
        path.write_bytes(data)
    except OSError:
        return None
    return path
