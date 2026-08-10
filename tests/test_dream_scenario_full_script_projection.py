from __future__ import annotations

from unittest.mock import patch


def _script() -> dict:
    return {
        "id": "projection_demo",
        "title": "Projection Demo",
        "author": "author-a",
        "stages": [
            {
                "id": "arrival",
                "name": "Arrival",
                "dramatic_task": "Task A",
                "entry_pressure": "Pressure A",
                "exit_signs": ["Exit A"],
                "not_yet_allowed": ["Forbidden A"],
                "drift_pressure": {"after_turns": 3, "instruction": "Drift A"},
            },
            {
                "id": "fracture",
                "name": "Fracture",
                "dramatic_task": "Task B",
                "entry_pressure": "Pressure B",
                "exit_signs": ["Exit B"],
                "not_yet_allowed": ["Forbidden B"],
            },
        ],
        "private_truths": [
            {
                "id": "truth-a",
                "truth": "Private truth A",
                "disclosure": {"arrival": {"policy": "hidden"}, "fracture": {"policy": "reveal_allowed"}},
            }
        ],
    }


def test_full_script_projection_contains_ordered_stages_and_private_policy():
    from core.dream.scenario_projection import render_full_script

    text = render_full_script(_script(), "arrival")
    assert "CURRENT STAGE ID: arrival; sequence: 1/2" in text
    for marker in ("Task A", "Pressure A", "Exit A", "Forbidden A", "Drift A", "Task B", "Pressure B", "Exit B", "Forbidden B"):
        assert marker in text
    assert "Private truth A" in text
    assert "reveal_allowed" in text
    assert text.index("id=arrival") < text.index("id=fracture")
    assert "cannot skip stages" in text


def test_strict_path_does_not_expand_when_full_renderer_is_available(monkeypatch):
    from core.dream.dream_prompt import _format_scenario_layer

    monkeypatch.setattr("core.dream.scenario_loader.load_script", lambda _script_id: _script())
    core = {"script_id": "projection_demo", "current_stage_id": "arrival"}
    strict = _format_scenario_layer(core)
    full = _format_scenario_layer(core, injection_mode="full_script")
    assert "Task A" in strict
    assert "Task B" not in strict
    assert "Task B" in full


def test_full_script_budget_is_explicit_and_strict_can_still_use_large_script(monkeypatch):
    import core.dream.scenario_projection as projection

    monkeypatch.setattr(
        projection,
        "_limits",
        lambda: {"max_stages": 1, "max_tokens": 1, "max_chars": 1},
    )
    budget = projection.validate_full_script_budget(_script())
    assert budget["ok"] is False
    assert "stage_count_exceeded" in budget["reasons"]
    assert "token_budget_exceeded" in budget["reasons"]
    assert "estimated_chars" in budget and "estimated_tokens" in budget


def test_projection_metadata_contains_counts_but_not_private_text(monkeypatch):
    from core.dream.scenario_projection import scenario_projection_metadata

    monkeypatch.setattr("core.dream.scenario_loader.load_script", lambda _script_id: _script())
    result = scenario_projection_metadata(
        {"script_id": "projection_demo", "current_stage_id": "arrival"},
        injection_mode="full_script",
    )
    assert result["mode"] == "full_script"
    assert result["stage_count"] == 2
    assert result["estimated_tokens"] > 0
    assert "Private truth A" not in str(result)
