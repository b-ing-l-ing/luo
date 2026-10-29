from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from typing import Any

from openai import AsyncOpenAI, BadRequestError, OpenAI

from .config import Settings

Message = dict[str, Any]


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


class AsyncChatLLM:
    """异步版本，供事件循环内的聊天使用。记忆抽取/摘要继续用同步客户端。"""

    def __init__(self, settings: Settings) -> None:
        if not settings.deepseek_api_key:
            raise RuntimeError("DEEPSEEK_API_KEY 未设置，请在 .env 里填写")
        self._client = AsyncOpenAI(
            api_key=settings.deepseek_api_key,
            base_url=settings.deepseek_base_url,
        )
        self._model = settings.deepseek_model

    async def stream(self, messages: list[Message]) -> AsyncIterator[str]:
        stream = await self._client.chat.completions.create(
            model=self._model,
            messages=messages,  # type: ignore[arg-type]
            stream=True,
        )
        async for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta

    async def complete(self, messages: list[Message], *, json_mode: bool = False) -> str:
        kwargs: dict[str, Any] = {}
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        try:
            resp = await self._client.chat.completions.create(
                model=self._model,
                messages=messages,  # type: ignore[arg-type]
                **kwargs,
            )
        except BadRequestError:
            if not json_mode:
                raise
            resp = await self._client.chat.completions.create(
                model=self._model,
                messages=messages,  # type: ignore[arg-type]
            )
        return resp.choices[0].message.content or ""

    async def stream_with_tools(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        execute_tool: Callable[[str, str], Awaitable[str]],
        *,
        max_rounds: int = 3,
    ) -> AsyncIterator[str]:
        """带工具调用的流式回合：模型要工具就执行，再把结果喂回去继续流式输出。"""
        msgs: list[dict[str, Any]] = list(messages)
        for _ in range(max_rounds):
            stream = await self._client.chat.completions.create(
                model=self._model,
                messages=msgs,  # type: ignore[arg-type]
                tools=tools,  # type: ignore[arg-type]
                tool_choice="auto",
                stream=True,
            )
            text_parts: list[str] = []
            calls: dict[int, dict[str, str]] = {}
            async for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                if delta.content:
                    text_parts.append(delta.content)
                    yield delta.content
                for call in delta.tool_calls or []:
                    entry = calls.setdefault(
                        call.index, {"id": "", "name": "", "arguments": ""}
                    )
                    if call.id:
                        entry["id"] = call.id
                    if call.function:
                        if call.function.name:
                            entry["name"] = call.function.name
                        if call.function.arguments:
                            entry["arguments"] += call.function.arguments
            if not calls:
                return

            msgs.append(
                {
                    "role": "assistant",
                    "content": "".join(text_parts) or None,
                    "tool_calls": [
                        {
                            "id": entry["id"],
                            "type": "function",
                            "function": {
                                "name": entry["name"],
                                "arguments": entry["arguments"],
                            },
                        }
                        for entry in calls.values()
                    ],
                }
            )
            for entry in calls.values():
                result = await execute_tool(entry["name"], entry["arguments"])
                msgs.append(
                    {
                        "role": "tool",
                        "tool_call_id": entry["id"],
                        "content": result,
                    }
                )
