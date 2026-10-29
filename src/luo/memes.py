from __future__ import annotations

import hashlib
import random
import re
from pathlib import Path
from typing import Any

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
MIME_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}

SEND_MEME_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "send_meme",
        "description": (
            "从本地梗图库挑一张图片发给用户。query 是情绪或场景标签，"
            "例如 无语、笑死、鼓掌、晚安、问号。只在自然合适时使用，不要每句都发。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "情绪/场景标签，例如 无语",
                }
            },
            "required": ["query"],
        },
    },
}


class MemeLibrary:
    def __init__(self, root: Path) -> None:
        self.root = root

    def files(self) -> list[Path]:
        if not self.root.exists():
            return []
        return sorted(
            path
            for path in self.root.iterdir()
            if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
        )

    def tags(self) -> list[str]:
        return [path.stem for path in self.files()]

    def find(
        self, query: str, rng: random.Random | None = None
    ) -> Path | None:
        files = self.files()
        if not files:
            return None
        text = str(query or "").strip().lower()
        rng = rng or random
        if not text:
            matches = files
        else:
            terms = [term for term in re.split(r"[\s,，、/]+", text) if term]
            matches = [
                path
                for path in files
                if any(term in path.stem.lower() for term in terms)
            ]
        if not matches:
            return None
        # 同类变体里随机挑，但越新的权重越高（1, 0.6, 0.36 ...）。
        matches = sorted(
            matches, key=lambda path: path.stat().st_mtime, reverse=True
        )[:10]
        weights = [0.6**index for index in range(len(matches))]
        return rng.choices(matches, weights=weights, k=1)[0]

    def mime_for(self, path: Path) -> str:
        return MIME_TYPES.get(path.suffix.lower(), "application/octet-stream")

    def has_same_content(self, data: bytes) -> bool:
        digest = hashlib.sha256(data).digest()
        for path in self.files():
            try:
                if hashlib.sha256(path.read_bytes()).digest() == digest:
                    return True
            except OSError:
                continue
        return False
