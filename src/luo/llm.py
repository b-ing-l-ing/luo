from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from openai import BadRequestError, OpenAI

from .config import Settings

Message = dict[str, str]


class ChatLLM:
    def __init__(self, settings: Settings) -> None:
        if not settings.deepseek_api_key:
            raise RuntimeError("DEEPSEEK_API_KEY 未设置，请在 .env 里填写")
        self._client = OpenAI(
            api_key=settings.deepseek_api_key,
            base_url=settings.deepseek_base_url,
        )
        self._model = settings.deepseek_model

    def stream(self, messages: list[Message]) -> Iterator[str]:
        stream = self._client.chat.completions.create(
            model=self._model,
            messages=messages,  # type: ignore[arg-type]
            stream=True,
        )
        for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta

    def complete(self, messages: list[Message], *, json_mode: bool = False) -> str:
        kwargs: dict[str, Any] = {}
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        try:
            resp = self._client.chat.completions.create(
                model=self._model,
                messages=messages,  # type: ignore[arg-type]
                **kwargs,
            )
        except BadRequestError:
            # 部分兼容端点不支持 json_object，退化成普通补全，解析层会容错。
            if not json_mode:
                raise
            resp = self._client.chat.completions.create(
                model=self._model,
                messages=messages,  # type: ignore[arg-type]
            )
        return resp.choices[0].message.content or ""
