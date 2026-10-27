"""游戏无关的核心接口。

约束：
- ReactivePolicy 同步、无 I/O、无 LLM，目标 <5ms。
- Planner / Speaker 异步，必须支持取消和截止时间。
- GameAdapter 只能执行 skills() 声明过的技能。
- 所有时间戳用单调时钟秒（`at`），不用墙上时间。
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, Protocol


class Priority(IntEnum):
    LOW = 0
    NORMAL = 1
    HIGH = 2
    CRITICAL = 3


@dataclass(frozen=True)
class Observation:
    """某一刻的世界状态快照。summary 给模型看，data 给适配器/策略用。"""

    game: str
    at: float
    summary: str
    data: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class GameEvent:
    """离散事件。CRITICAL 可以绕过 LLM 直接触发反射策略。"""

    game: str
    at: float
    type: str
    priority: Priority = Priority.NORMAL
    data: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SkillSpec:
    """适配器声明的技能。parameters 是 JSON Schema。"""

    name: str
    description: str
    parameters: Mapping[str, Any]
    priority: Priority = Priority.NORMAL
    timeout_s: float = 10.0


@dataclass(frozen=True)
class Action:
    """一次技能调用。deadline 是单调时钟秒，过期就不再执行。"""

    skill: str
    args: Mapping[str, Any] = field(default_factory=dict)
    priority: Priority = Priority.NORMAL
    deadline: float | None = None


@dataclass(frozen=True)
class SkillResult:
    ok: bool
    message: str = ""
    data: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Decision:
    """规划器的输出：可以只说话、只行动，或同时。"""

    speech: str | None = None
    actions: tuple[Action, ...] = ()
    urgency: Priority = Priority.NORMAL
    reason: str = ""


@dataclass(frozen=True)
class PlannerContext:
    """给规划器的上下文。memory 已经是压缩后的文本块。"""

    observation: Observation
    events: tuple[GameEvent, ...]
    memory: str
    persona: str
    open_loops: tuple[str, ...] = ()
    deadline: float | None = None


class GameAdapter(Protocol):
    """游戏侧唯一需要实现的接口。"""

    @property
    def name(self) -> str: ...

    async def start(self) -> None: ...

    async def stop(self) -> None: ...

    async def observe(self) -> Observation: ...

    def events(self) -> AsyncIterator[GameEvent]: ...

    def skills(self) -> tuple[SkillSpec, ...]: ...

    async def execute(self, action: Action) -> SkillResult: ...

    async def cancel_all(self) -> None:
        """取消当前所有动作并回到安全状态。"""
        ...


class ReactivePolicy(Protocol):
    """同步快路径：不得做 I/O、不得调 LLM。"""

    def react(
        self, event: GameEvent, observation: Observation
    ) -> tuple[Action, ...]: ...


class Planner(Protocol):
    """异步慢路径：可以调 LLM，但必须尊重 context.deadline。"""

    async def decide(self, context: PlannerContext) -> Decision: ...


class Speaker(Protocol):
    async def say(self, text: str, *, priority: Priority = Priority.NORMAL) -> None: ...


class ChatChannel(Protocol):
    """终端 / QQ 等聊天通道。"""

    async def start(
        self, on_message: Callable[[str], Awaitable[None]]
    ) -> None: ...

    async def send(self, text: str) -> None: ...

    async def stop(self) -> None: ...


class Scheduler(Protocol):
    """事件总线 + 抢占 + 计划生命周期。"""

    async def run(self) -> None: ...

    async def submit(self, event: GameEvent) -> None: ...

    async def shutdown(self) -> None: ...
