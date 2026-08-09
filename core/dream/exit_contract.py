"""Machine-readable Dream exit contract and exit metadata helpers.

The visible Dream transcript is narrative data.  Closing a session must only
be driven by this explicit, local-parsed control block or by the hard-exit
endpoint; never by scanning assistant prose for exit words.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any


DREAM_CONTROL_TAG = "dream_control"
DREAM_CONTROL_ACCEPT = "accept"
DREAM_CONTROL_STAY = "stay"
CONTROL_MISSING = "control_missing"
CONTROL_INVALID = "control_invalid"
CONTROL_ACCEPTED = "accepted"
CONTROL_DECLINED = "declined"
CONTROL_ABSENT = "absent"

EXIT_MECHANISM_CHARACTER_ACCEPT = "character_accept"
EXIT_MECHANISM_USER_HARD_EXIT = "user_hard_exit"
EXIT_MECHANISM_SYSTEM_FALLBACK = "system_fallback"
EXIT_MECHANISMS = frozenset({
    EXIT_MECHANISM_CHARACTER_ACCEPT,
    EXIT_MECHANISM_USER_HARD_EXIT,
    EXIT_MECHANISM_SYSTEM_FALLBACK,
})

EXIT_INITIATOR_USER = "user"
EXIT_INITIATOR_CHARACTER = "character"
EXIT_INITIATOR_SYSTEM = "system"
EXIT_INITIATORS = frozenset({
    EXIT_INITIATOR_USER,
    EXIT_INITIATOR_CHARACTER,
    EXIT_INITIATOR_SYSTEM,
})

COMPLETION_COMPLETE = "complete"
COMPLETION_INTERRUPTED = "interrupted"
COMPLETION_UNKNOWN = "unknown"
COMPLETIONS = frozenset({
    COMPLETION_COMPLETE,
    COMPLETION_INTERRUPTED,
    COMPLETION_UNKNOWN,
})

EXIT_REASON_CHARACTER_ACCEPTED = "character_accepted"
EXIT_REASON_USER_HARD_EXIT = "user_hard_exit"
EXIT_REASON_SYSTEM_FALLBACK = "system_fallback"
EXIT_REASON_CONTROL_MISSING = "control_missing"
EXIT_REASON_CONTROL_INVALID = "control_invalid"
EXIT_REASONS = frozenset({
    EXIT_REASON_CHARACTER_ACCEPTED,
    EXIT_REASON_USER_HARD_EXIT,
    EXIT_REASON_SYSTEM_FALLBACK,
    EXIT_REASON_CONTROL_MISSING,
    EXIT_REASON_CONTROL_INVALID,
})

COMPLETION_MIN_ASSISTANT_TURNS = 5

_CONTROL_RE = re.compile(
    r"<dream_control>\s*(.*?)\s*</dream_control>",
    re.DOTALL,
)


@dataclass(frozen=True)
class DreamControlParse:
    visible_reply: str
    decision: str | None
    status: str


def parse_dream_control(reply: str) -> DreamControlParse:
    """Strip and validate the one supported Dream control block.

    JSON parsing is deliberately strict.  A malformed block is still removed
    from user-visible/archive content, but it cannot close the Dream.
    """
    match = _CONTROL_RE.search(reply)
    if not match:
        return DreamControlParse(reply, None, CONTROL_ABSENT)

    visible = (reply[: match.start()] + reply[match.end() :]).strip()
    try:
        payload = json.loads(match.group(1).strip())
    except (TypeError, ValueError, json.JSONDecodeError):
        return DreamControlParse(visible, None, CONTROL_INVALID)

    if not isinstance(payload, dict) or payload.get("exit") not in {
        DREAM_CONTROL_ACCEPT,
        DREAM_CONTROL_STAY,
    }:
        return DreamControlParse(visible, None, CONTROL_INVALID)

    decision = str(payload["exit"])
    return DreamControlParse(
        visible,
        decision,
        CONTROL_ACCEPTED if decision == DREAM_CONTROL_ACCEPT else CONTROL_DECLINED,
    )


def completion_for_exit(mechanism: str, assistant_turns: int) -> str:
    """Classify completion without looking at narrative keywords.

    A character acceptance is an explicit complete close.  A user hard exit
    after a sufficiently long transcript is treated as a completed session;
    short hard exits remain interrupted.  Unknown/system paths stay unknown.
    """
    if mechanism == EXIT_MECHANISM_CHARACTER_ACCEPT:
        return COMPLETION_COMPLETE
    if mechanism == EXIT_MECHANISM_USER_HARD_EXIT:
        return (
            COMPLETION_COMPLETE
            if assistant_turns >= COMPLETION_MIN_ASSISTANT_TURNS
            else COMPLETION_INTERRUPTED
        )
    return COMPLETION_UNKNOWN


def public_control_observation(
    *,
    status: str,
    dream_id: str,
    ts: float,
    reason: str | None = None,
) -> dict[str, Any]:
    """Return the fixed, text-free shape exposed by read-only state APIs."""
    return {
        "status": status,
        "reason_code": reason or status,
        "dream_id": dream_id,
        "ts": float(ts),
    }

