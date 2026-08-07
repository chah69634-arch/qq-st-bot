"""Small typed vocabulary for the Self Capability P0 boundary."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


Action = Literal["enable", "disable", "set_value"]


@dataclass(frozen=True)
class CapabilityChange:
    action: Action
    capability_id: str
    value: Any
    reason: str
    expected_revision: int
    action_id: str


@dataclass(frozen=True)
class ChangeResult:
    ok: bool
    code: str
    revision: int
    value: Any = None
    message: str = ""


def state_template(uid: str, char_id: str) -> dict[str, Any]:
    return {
        "version": 1,
        "uid": str(uid),
        "char_id": str(char_id),
        "grants": {},
        "agent_state": {},
        "agent_baseline": {},
        "locks": {},
        "applied_actions": {},
        "revision": 0,
        "updated_at": 0.0,
    }
