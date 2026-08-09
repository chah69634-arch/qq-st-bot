from __future__ import annotations

import copy

import pytest


def _core(stage_id: str) -> dict:
    return {
        "script_id": "private_truth_demo",
        "current_stage_id": stage_id,
        "stage_turns": 0,
        "stall_turns": 0,
        "ending_state": None,
    }


def test_private_truth_hidden_policy_preserves_knowledge_without_future_leak():
    from core.dream.dream_prompt import _format_scenario_layer

    text = _format_scenario_layer(_core("arrival"))

    assert "The masked stranger and the later rescuer are the same person." in text
    assert "不要把自己演成对此失忆或刚刚才发现" in text
    assert "必须隐藏真相" in text
    assert "He knows the locked room too well." not in text
    assert "His keys use the same unusual metal." not in text
    assert "本阶段必须让真相在剧情中落地" not in text
    assert "The old mask is lying on the table." not in text


def test_private_truth_hint_policy_only_exposes_current_stage_allowed_hints():
    from core.dream.dream_prompt import _format_scenario_layer

    text = _format_scenario_layer(_core("shelter"))

    assert "只可通过下列线索含蓄表现" in text
    assert "He knows the locked room too well." in text
    assert "His keys use the same unusual metal." in text
    assert "The old mask is lying on the table." not in text
    assert "必须让真相在剧情中落地" not in text


def test_private_truth_reveal_required_is_current_stage_only():
    from core.dream.dream_prompt import _format_scenario_layer

    text = _format_scenario_layer(_core("reveal"))

    assert "必须让真相在剧情中落地" in text
    assert "He knows the locked room too well." not in text


def test_private_truth_schema_rejects_unknown_stage_and_policy():
    from core.dream.scenario_loader import _validate_script, load_script

    script = load_script("private_truth_demo")
    unknown_stage = copy.deepcopy(script)
    unknown_stage["private_truths"][0]["disclosure"]["future"] = {"policy": "hidden"}
    with pytest.raises(ValueError, match="unknown stage"):
        _validate_script(unknown_stage)

    invalid_policy = copy.deepcopy(script)
    invalid_policy["private_truths"][0]["disclosure"]["arrival"]["policy"] = "spoilers_ok"
    with pytest.raises(ValueError, match="policy is invalid"):
        _validate_script(invalid_policy)


def test_existing_scenario_without_private_truths_remains_valid():
    from core.dream.scenario_loader import _validate_script, load_script

    script = load_script("prison_demo")
    assert "private_truths" not in script
    _validate_script(script)
