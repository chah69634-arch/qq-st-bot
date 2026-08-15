"""Brief 166: Scenario must hard-disable D4 while Sandbox keeps the positive control."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock


_CHARACTER = MagicMock()
_CHARACTER.name = "Test Companion"
_CHARACTER.description = "A test character"
_CHARACTER.gender = "neutral"


def _snapshot() -> dict[str, Any]:
    return {
        "created_at": 1,
        "user_id": "scenario-d4-test",
        "entry_reason": "PRIVATE_ENTRY_REASON",
        "relationship_state": {"summary": "PRIVATE_RELATIONSHIP"},
        "recent_reality_context": "PRIVATE_RECENT_REALITY",
        "episodic_summary": "PRIVATE_EPISODIC",
        "mid_term_context": "PRIVATE_MID_TERM",
        "profile_impression": "PRIVATE_PROFILE_IMPRESSION",
    }


def _scenario_core() -> dict[str, Any]:
    return {
        "script_id": "prison_demo",
        "current_stage_id": "arrival",
        "stage_turns": 0,
        "ending_state": None,
    }


def _build(mode: str, capture: dict[str, Any]) -> list[dict[str, str]]:
    from core.dream.dream_prompt import build_dream_prompt

    return build_dream_prompt(
        character=_CHARACTER,
        user_id="scenario-d4-test",
        user_message="当前用户输入",
        context_snapshot=_snapshot(),
        dream_history=[],
        local_state={},
        dream_mode=mode,
        scenario_core=_scenario_core() if mode == "scenario" else None,
        _capture_hook=capture.update,
    )


def test_scenario_d4_is_hard_disabled_in_messages_and_inspector():
    capture: dict[str, Any] = {}
    messages = _build("scenario", capture)
    joined = "\n".join(message["content"] for message in messages)

    assert "D4·入梦前背景" not in joined
    for marker in (
        "PRIVATE_ENTRY_REASON",
        "PRIVATE_RELATIONSHIP",
        "PRIVATE_RECENT_REALITY",
        "PRIVATE_EPISODIC",
        "PRIVATE_MID_TERM",
        "PRIVATE_PROFILE_IMPRESSION",
    ):
        assert marker not in joined

    d4 = next(layer for layer in capture["layers"] if layer["label"] == "D4_frozen_reality")
    assert d4["injected"] is False
    assert d4["flags"] == ["DISABLED"]
    assert d4["note"] == "scenario_profile"
    assert not d4["content"]


def test_sandbox_d4_remains_injected_as_positive_control():
    capture: dict[str, Any] = {}
    messages = _build("sandbox", capture)
    joined = "\n".join(message["content"] for message in messages)

    assert "D4·入梦前背景" in joined
    assert "PRIVATE_RECENT_REALITY" in joined
    d4 = next(layer for layer in capture["layers"] if layer["label"] == "D4_frozen_reality")
    assert d4["injected"] is True
    assert d4["flags"] == []
