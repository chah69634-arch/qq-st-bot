"""Brief 166: one-shot Scenario recovery cues and stall pressure."""

from __future__ import annotations

import asyncio
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch


_UID = "brief166_recovery"
_CHARACTER = MagicMock()
_CHARACTER.name = "Test Companion"
_CHARACTER.description = "A test character"
_CHARACTER.gender = "neutral"
_SNAPSHOT: dict[str, Any] = {
    "created_at": time.time(),
    "user_id": _UID,
    "entry_reason": "test",
    "relationship_state": {},
    "recent_reality_context": "",
    "episodic_summary": "",
    "mid_term_context": "",
    "profile_impression": "",
}
_MESSAGES = [{"role": "system", "content": "sys"}, {"role": "user", "content": "hi"}]


def _core(**updates: Any) -> dict[str, Any]:
    value: dict[str, Any] = {
        "script_id": "prison_demo",
        "current_stage_id": "arrival",
        "stage_turns": 0,
        "stall_turns": 0,
        "recovery_pending": False,
        "ending_state": None,
    }
    value.update(updates)
    return value


def test_recovery_prompt_is_current_stage_only_and_natural():
    from core.dream.dream_prompt import _format_scenario_layer

    text = _format_scenario_layer(_core(
        recovery_pending=True,
        last_blocked_events=["立即交换秘密"],
    ))

    assert "【接住刚才的意图】" in text
    assert "囚犯与看守第一次真实地交谈" in text
    assert "立即交换秘密" in text
    assert "秘密交换" not in text
    assert "裂缝" not in text
    assert "系统纠偏" not in text
    assert "偏离剧本" not in text


def test_recovery_is_not_injected_without_pending_flag():
    from core.dream.dream_prompt import _format_scenario_layer

    text = _format_scenario_layer(_core(last_blocked_events=["立即交换秘密"]))
    assert "【接住刚才的意图】" not in text


def test_drift_pressure_uses_stall_turns_not_total_stage_turns():
    from core.dream.dream_prompt import _format_scenario_layer

    not_stalled = _format_scenario_layer(_core(stage_turns=99, stall_turns=0))
    stalled = _format_scenario_layer(_core(stage_turns=1, stall_turns=6))
    assert "漂移压力" not in not_stalled
    assert "漂移压力" in stalled
    assert "巡视时间" in stalled


def test_generic_recovery_for_stage_without_drift_pressure_has_no_new_fact():
    from core.dream.dream_prompt import _format_scenario_layer

    text = _format_scenario_layer(_core(
        current_stage_id="fracture",
        stall_turns=2,
    ))
    assert "轻量拉回" in text
    assert "让既有信任接受一次明确考验" in text
    assert "秘密交换" not in text


def test_prompt_inspector_reports_recovery_and_drift_injection():
    from core.dream.dream_prompt import build_dream_prompt

    capture: dict[str, Any] = {}
    build_dream_prompt(
        character=_CHARACTER,
        user_id=_UID,
        user_message="用户输入",
        context_snapshot=_SNAPSHOT,
        dream_history=[],
        local_state={},
        dream_mode="scenario",
        scenario_core=_core(
            recovery_pending=True,
            last_blocked_events=["立即交换秘密"],
            stall_turns=6,
        ),
        _capture_hook=capture.update,
    )
    assert capture["scenario_observation"] == {
        "current_stage_id": "arrival",
        "stall_turns": 6,
        "recovery_injected": True,
        "drift_pressure_injected": True,
        "generic_recovery_injected": False,
        "injection_mode": "strict_stage",
    }


def _enter(uid: str, sandbox) -> MagicMock:
    from core.dream.dream_pipeline import enter_dream
    from core.dream.dream_settings import save

    save(uid, {"enable_dream_lorebook": False})
    pipeline = MagicMock()
    pipeline.character = _CHARACTER
    with (
        patch("core.dream.dream_context.build_snapshot", new=AsyncMock(return_value=dict(_SNAPSHOT))),
        patch("core.pipeline_registry.get", return_value=pipeline),
        patch("core.dream.dream_hud.delete_hud_state"),
    ):
        result = asyncio.run(enter_dream(uid, char_id="yexuan", dream_mode="scenario", script_id="prison_demo"))
    assert result["ok"] is True
    return pipeline


def _turn(uid: str, pipeline: MagicMock, reply: str, *, capture: dict[str, Any] | None = None) -> dict[str, Any]:
    from core.dream.dream_pipeline import dream_turn
    from core.dream.dream_state import read_state
    from core.dream import dream_prompt
    real_build_dream_prompt = dream_prompt.build_dream_prompt

    def _build(*args: Any, **kwargs: Any) -> list[dict[str, str]]:
        if capture is not None:
            capture["scenario_core"] = dict(kwargs.get("scenario_core") or {})
        return real_build_dream_prompt(*args, **kwargs)

    with (
        patch("core.dream.dream_log.read_current", return_value=[]),
        patch("core.dream.dream_log.append_turn"),
        patch("core.pipeline_registry.get", return_value=pipeline),
        patch("core.dream.dream_prompt.build_dream_prompt", side_effect=_build),
        patch("core.llm_client.chat", new=AsyncMock(return_value=reply)),
        patch("core.dream.body_tracker.analyze_turn", return_value=MagicMock(to_dict=lambda: {})),
        patch("core.dream.body_projection.project_body_for_yexuan", return_value={"d5_text": "", "yexuan_tension": 0.0}),
        patch("core.narrative_parser.parse_narrative_segments", return_value={"segments": [], "content": "reply"}),
    ):
        result = asyncio.run(dream_turn(uid, "用户输入"))
    assert result.get("error") is None
    return read_state(uid)["scenario_core"]


def _reply(signal: str, exits: list[str] | None = None, blocked: list[str] | None = None) -> str:
    import json

    control = {
        "progress_signal": signal,
        "matched_exit_signs": exits or [],
        "blocked_events": blocked or [],
    }
    return f"reply\n<scenario_control>{json.dumps(control, ensure_ascii=False)}</scenario_control>"


def test_blocked_event_is_injected_once_then_consumed(sandbox):
    pipeline = _enter(_UID, sandbox)
    blocked = _turn(_UID, pipeline, _reply("not_close", blocked=["立即交换秘密"]))
    assert blocked["recovery_pending"] is True
    assert blocked["stall_turns"] == 1

    capture: dict[str, Any] = {}
    next_state = _turn(_UID, pipeline, _reply("not_close"), capture=capture)
    prompt_core = capture["scenario_core"]
    assert prompt_core["recovery_pending"] is True
    assert next_state["recovery_pending"] is False
    assert next_state["last_blocked_events"] == []


def test_stage_transition_clears_recovery_and_stall_state(sandbox):
    pipeline = _enter(_UID + "_transition", sandbox)
    _turn(_UID + "_transition", pipeline, _reply("not_close", blocked=["立即交换秘密"]))
    state = _turn(
        _UID + "_transition",
        pipeline,
        _reply("satisfied", ["她说出了自己的名字"]),
    )

    assert state["current_stage_id"] == "negotiation"
    assert state["stall_turns"] == 0
    assert state["recovery_pending"] is False
    assert state["last_blocked_events"] == []


def test_approaching_reduces_stall_after_missing_turn(sandbox):
    uid = _UID + "_stall"
    pipeline = _enter(uid, sandbox)
    first = _turn(uid, pipeline, "reply without control")
    assert first["stall_turns"] == 1
    second = _turn(uid, pipeline, _reply("approaching"))
    assert second["stall_turns"] == 0
