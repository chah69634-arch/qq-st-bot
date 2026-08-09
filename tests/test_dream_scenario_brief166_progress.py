"""Brief 166: deterministic Scenario progress normalization and adjudication."""

from __future__ import annotations

import asyncio
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch


_UID = "brief166_progress"
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
_FAKE_MESSAGES = [{"role": "system", "content": "sys"}, {"role": "user", "content": "hi"}]


def _control(
    signal: str,
    exits: list[str] | None = None,
    blocked: list[str] | None = None,
    *,
    extra: str = "",
) -> str:
    import json

    data = {
        "progress_signal": signal,
        "matched_exit_signs": exits or [],
        "blocked_events": blocked or [],
    }
    return f"reply\n<scenario_control>{json.dumps(data, ensure_ascii=False)}{extra}</scenario_control>"


def test_normalize_filters_and_deduplicates_current_stage_whitelists():
    from core.dream.dream_pipeline import _normalize_scenario_control

    result = _normalize_scenario_control(
        {
            "progress_signal": "satisfied",
            "matched_exit_signs": ["她说出了自己的名字", "她说出了自己的名字", "future"],
            "blocked_events": ["立即交换秘密", "unknown", "立即交换秘密"],
        },
        {
            "exit_signs": ["她说出了自己的名字"],
            "not_yet_allowed": ["立即交换秘密"],
        },
    )

    assert result["matched_exit_signs"] == ["她说出了自己的名字"]
    assert result["blocked_events"] == ["立即交换秘密"]
    assert result["valid_exit_sign_count"] == 1
    assert result["unknown_exit_sign_count"] == 1
    assert result["unknown_blocked_event_count"] == 1


def test_v2_control_maps_current_stage_ids_and_discards_unknown_ids():
    from core.dream.dream_pipeline import _adjudicate_scenario_progress, _normalize_scenario_control

    stage = {
        "exit_signs": ["first action", "second action"],
        "not_yet_allowed": ["secret reveal"],
    }
    normalized = _normalize_scenario_control(
        {
            "control_version": 2,
            "hit": ["E2", "E99", "E2"],
            "blocked": ["B1", "B9"],
        },
        stage,
    )

    assert normalized["status"] == "valid"
    assert normalized["control_version"] == 2
    assert normalized["matched_exit_ids"] == ["E2"]
    assert normalized["blocked_ids"] == ["B1"]
    assert normalized["matched_exit_signs"] == ["E2"]
    assert normalized["blocked_events"] == ["B1"]
    assert normalized["unknown_exit_sign_count"] == 1
    assert normalized["unknown_blocked_event_count"] == 1
    decision = _adjudicate_scenario_progress(
        normalized,
        current_stage=stage,
        next_stage={"id": "next"},
        ending_state=None,
        scenario_arc_mode="linear",
        current_bucket="low",
    )
    assert decision["disposition"] == "advanced"
    assert decision["advance_to"] == "next"


def test_v2_control_without_current_stage_hit_cannot_advance():
    from core.dream.dream_pipeline import _adjudicate_scenario_progress, _normalize_scenario_control

    normalized = _normalize_scenario_control(
        {"control_version": 2, "hit": ["E99"], "blocked": []},
        {"exit_signs": ["current"]},
    )
    decision = _adjudicate_scenario_progress(
        normalized,
        current_stage={"exit_signs": ["current"]},
        next_stage={"id": "next"},
        ending_state=None,
        scenario_arc_mode="linear",
        current_bucket="low",
    )
    assert normalized["progress_signal"] == "not_close"
    assert decision["disposition"] == "no_progress"
    assert decision["advance_to"] is None


def test_next_stage_is_not_a_parser_or_adjudication_instruction():
    from core.dream.dream_pipeline import (
        _adjudicate_scenario_progress,
        _extract_scenario_control,
        _normalize_scenario_control,
    )

    visible, parsed = _extract_scenario_control(
        'reply<scenario_control>{"progress_signal":"satisfied",'
        '"matched_exit_signs":["current"],"blocked_events":[],"next_stage":"fracture"}'
        "</scenario_control>"
    )
    assert "scenario_control" not in visible
    assert "next_stage" not in parsed
    normalized = _normalize_scenario_control(
        {**parsed, "matched_exit_signs": ["current"]},
        {"exit_signs": ["current"]},
    )
    decision = _adjudicate_scenario_progress(
        normalized,
        current_stage={"exit_signs": ["current"]},
        next_stage={"id": "yaml_next"},
        ending_state=None,
        scenario_arc_mode="linear",
        current_bucket="low",
    )
    assert decision["advance_to"] == "yaml_next"


def test_satisfied_without_valid_exit_is_not_completion():
    from core.dream.dream_pipeline import _adjudicate_scenario_progress, _normalize_scenario_control

    normalized = _normalize_scenario_control(
        {"progress_signal": "satisfied", "matched_exit_signs": ["later-stage"], "blocked_events": []},
        {"exit_signs": ["current-stage"]},
    )
    decision = _adjudicate_scenario_progress(
        normalized,
        current_stage={"exit_signs": ["current-stage"]},
        next_stage={"id": "next"},
        ending_state=None,
        scenario_arc_mode="linear",
        current_bucket="low",
    )
    assert decision["advance_to"] is None
    assert decision["disposition"] == "satisfied_without_valid_exit_sign"


def test_arc_block_has_fixed_reason_and_coarse_buckets():
    from core.dream.dream_pipeline import _adjudicate_scenario_progress, _normalize_scenario_control

    normalized = _normalize_scenario_control(
        {"progress_signal": "satisfied", "matched_exit_signs": ["done"], "blocked_events": []},
        {"exit_signs": ["done"], "arc": "high"},
    )
    decision = _adjudicate_scenario_progress(
        normalized,
        current_stage={"exit_signs": ["done"], "arc": "high"},
        next_stage={"id": "next"},
        ending_state=None,
        scenario_arc_mode="arc",
        current_bucket="rising",
    )
    assert decision["advance_to"] is None
    assert decision["disposition"] == "arc_blocked"
    assert decision["blocked_reason"] == "arc_target_not_reached"
    assert decision["blocked_current_bucket"] == "rising"
    assert decision["blocked_target_bucket"] == "high"


def test_old_scenario_state_loads_with_new_observation_defaults():
    from core.dream.scenario_core import ScenarioCore

    state = ScenarioCore.from_dict({"script_id": "prison_demo", "current_stage_id": "arrival"})
    assert state.stage_turns == 0
    assert state.satisfied_streak == 0
    assert state.last_unknown_exit_sign_count == 0
    assert state.advance_disposition is None


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


def _turn(uid: str, pipeline: MagicMock, reply: str) -> dict[str, Any]:
    from core.dream.dream_pipeline import dream_turn
    from core.dream.dream_state import read_state

    with (
        patch("core.dream.dream_log.read_current", return_value=[]),
        patch("core.dream.dream_log.append_turn"),
        patch("core.pipeline_registry.get", return_value=pipeline),
        patch("core.dream.dream_prompt.build_dream_prompt", return_value=_FAKE_MESSAGES),
        patch("core.llm_client.chat", new=AsyncMock(return_value=reply)),
        patch("core.dream.body_tracker.analyze_turn", return_value=MagicMock(to_dict=lambda: {})),
        patch("core.dream.body_projection.project_body_for_yexuan", return_value={"d5_text": "", "yexuan_tension": 0.0}),
        patch("core.narrative_parser.parse_narrative_segments", return_value={"segments": [], "content": "reply"}),
    ):
        result = asyncio.run(dream_turn(uid, "用户输入"))
    assert result.get("error") is None
    return read_state(uid)["scenario_core"]


def test_one_valid_exit_advances_linear_stage(sandbox):
    pipeline = _enter(_UID, sandbox)
    state = _turn(_UID, pipeline, _control("satisfied", ["她说出了自己的名字"]))

    assert state["current_stage_id"] == "negotiation"
    assert state["stage_turns"] == 0
    assert state["advance_disposition"] == "advanced"
    assert state["last_valid_exit_sign_count"] == 1


def test_unknown_exit_cannot_advance(sandbox):
    pipeline = _enter(_UID, sandbox)
    state = _turn(_UID, pipeline, _control("satisfied", ["后续阶段完成信号"]))

    assert state["current_stage_id"] == "arrival"
    assert state["advance_disposition"] == "satisfied_without_valid_exit_sign"
    assert state["last_valid_exit_sign_count"] == 0
    assert state["last_unknown_exit_sign_count"] == 1


def test_missing_and_invalid_controls_have_distinct_dispositions(sandbox):
    pipeline = _enter(_UID, sandbox)
    missing = _turn(_UID, pipeline, "reply without control")
    assert missing["advance_disposition"] == "control_missing"
    invalid = _turn(_UID, pipeline, "reply<scenario_control>{not-json}</scenario_control>")
    assert invalid["advance_disposition"] == "control_invalid"
