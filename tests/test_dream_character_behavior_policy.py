from types import SimpleNamespace
from unittest.mock import patch

from core.dream.dream_prompt import build_dream_prompt, dump_dream_prompt


def _character(behavior=None):
    return SimpleNamespace(
        name="Test Character",
        description="A stable authored persona.",
        personality="PERSONALITY_FROM_CARD",
        system_prompt="SYSTEM_PROMPT_FROM_CARD",
        gender="neutral",
        presence_ext={"dream_behavior": behavior} if behavior is not None else {},
    )


def _build(*, mode="sandbox", behavior=None, scenario_core=None):
    return dump_dream_prompt(build_dream_prompt(
        character=_character(behavior),
        user_id="dream_behavior_user",
        user_message="continue",
        context_snapshot={},
        dream_history=[],
        local_state={},
        dream_mode=mode,
        scenario_core=scenario_core,
    ))


def test_shared_director_keeps_protocol_but_has_no_global_softening_policy():
    system = _build()
    assert "SYSTEM_PROMPT_FROM_CARD" in system
    assert "PERSONALITY_FROM_CARD" in system
    assert "/stop" in system
    assert "不替角色规定温柔、强硬、退让或升级" in system
    assert "立即以" not in system
    assert "柔化场景或过渡出去" not in system
    assert "对你的情感取向，在任何世界规则下保持不变" not in system


def test_character_card_directives_are_selected_by_dream_mode():
    behavior = {
        "identity_anchor": "ANCHOR_ALWAYS",
        "sandbox_directive": "SANDBOX_ONLY",
        "scenario_directive": "SCENARIO_ONLY",
    }
    sandbox = _build(behavior=behavior)
    assert "ANCHOR_ALWAYS" in sandbox
    assert "SANDBOX_ONLY" in sandbox
    assert "SCENARIO_ONLY" not in sandbox

    script = {
        "id": "demo",
        "title": "Demo",
        "stages": [{
            "id": "stage_1",
            "name": "Stage One",
            "dramatic_task": "Keep the current stance.",
            "entry_pressure": "The door is closed.",
            "exit_signs": [],
        }],
    }
    with patch("core.dream.scenario_loader.load_script", return_value=script):
        scenario = _build(
            mode="scenario",
            behavior=behavior,
            scenario_core={"script_id": "demo", "current_stage_id": "stage_1"},
        )
    assert "ANCHOR_ALWAYS" in scenario
    assert "SCENARIO_ONLY" in scenario
    assert "SANDBOX_ONLY" not in scenario
    assert "本轮行动契约" in scenario
    assert "只有口头威胁、重复警告或气氛描写不算行动推进" in scenario
    assert "内在关心、依恋或犹豫" in scenario


def test_malformed_character_behavior_is_ignored():
    system = _build(behavior="not-a-mapping")
    assert "角色卡梦境人格锚点" not in system
