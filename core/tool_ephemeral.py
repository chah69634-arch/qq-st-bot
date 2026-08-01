"""Ephemeral status events for tool-loop UI feedback.

These events are deliberately in-memory only. They never enter a conversation
turn, prompt history, memory pipeline, action trace, or durable channel queue.
"""
from __future__ import annotations

import inspect
import logging
import time
from dataclasses import dataclass
from typing import Awaitable, Callable, Literal

logger = logging.getLogger(__name__)

ToolEphemeralKind = Literal[
    "pending_confirmation",
    "queued",
    "waiting",
    "finished",
    "failed",
    "outcome_unknown",
    "cancelled",
]

TOOL_EPHEMERAL_KINDS = frozenset({
    "pending_confirmation",
    "queued",
    "waiting",
    "finished",
    "failed",
    "outcome_unknown",
    "cancelled",
})
DEFAULT_TTL_S = 20.0
_DISPLAY_TEXT = {
    "pending_confirmation": "",
    "queued": "我先处理一下。",
    "waiting": "还在等回应，稍等我一下。",
    "finished": "",
    "failed": "",
    "outcome_unknown": "这边没能确认结果。",
    "cancelled": "我已经停止等待了，结果还不能确认。",
}


@dataclass(frozen=True)
class ToolEphemeralEvent:
    """A short-lived UI-only status update for one serial tool call."""

    status_id: str
    kind: ToolEphemeralKind
    tool_name: str
    index: int
    total: int
    attempt: int = 1
    ttl_s: float = DEFAULT_TTL_S
    emitted_at: float = 0.0
    tts_allowed: bool = False

    def __post_init__(self) -> None:
        if self.kind not in TOOL_EPHEMERAL_KINDS:
            raise ValueError(f"unsupported tool ephemeral kind: {self.kind}")
        if self.index < 1 or self.total < self.index:
            raise ValueError("tool ephemeral index/total must describe a serial batch")
        if self.attempt < 1:
            raise ValueError("tool ephemeral attempt must be positive")
        if self.ttl_s <= 0:
            raise ValueError("tool ephemeral TTL must be positive")
        if self.emitted_at <= 0:
            object.__setattr__(self, "emitted_at", time.time())

    @property
    def expires_at(self) -> float:
        return self.emitted_at + self.ttl_s

    def is_expired(self, *, now: float | None = None) -> bool:
        return (time.time() if now is None else now) >= self.expires_at

    def should_deliver(self, *, now: float | None = None) -> bool:
        """Consumers must not replay an expired transient status."""
        return not self.is_expired(now=now)

    @property
    def display_text(self) -> str:
        """Bounded UI text; never expose the model's raw tool-call content."""
        return _DISPLAY_TEXT[self.kind]


ToolEventObserver = Callable[[ToolEphemeralEvent], Awaitable[None] | None]


async def notify(observer: ToolEventObserver | None, event: ToolEphemeralEvent) -> None:
    """Deliver one transient event without letting UI failures affect a tool call."""
    if observer is None or event.is_expired():
        return
    try:
        result = observer(event)
        if inspect.isawaitable(result):
            await result
    except Exception:
        logger.warning(
            "[tool_ephemeral] observer failed status=%s kind=%s",
            event.status_id,
            event.kind,
            exc_info=True,
        )
