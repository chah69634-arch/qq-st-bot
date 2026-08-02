"""Process-local fail-closed guard for recovery validation."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Iterator


class OutboundAttempted(RuntimeError):
    pass


@dataclass
class NoOutboundGuard:
    attempts: list[str] = field(default_factory=list)

    def block(self, boundary: str) -> None:
        self.attempts.append(boundary)
        raise OutboundAttempted(f"recovery validation blocked outbound boundary: {boundary}")


_ACTIVE: ContextVar[NoOutboundGuard | None] = ContextVar("presencekit_no_outbound", default=None)


@contextmanager
def recovery_no_outbound() -> Iterator[NoOutboundGuard]:
    guard = NoOutboundGuard()
    token = _ACTIVE.set(guard)
    try:
        yield guard
    finally:
        _ACTIVE.reset(token)


def assert_outbound_allowed(boundary: str) -> None:
    guard = _ACTIVE.get()
    if guard is not None:
        guard.block(boundary)
