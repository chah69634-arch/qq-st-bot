from types import SimpleNamespace
from unittest.mock import patch

from core.dream.dream_prompt import build_dream_prompt, dump_dream_prompt
from core.dream.scenario_profile import scenario_identity_projection


def _character(*, scenario_identity=None):
    behavior = {
        "identity_anchor": "COMMON_ANCHOR",
        "scenario_directive": "SCENARIO_DIRECTIVE",
    }
    if scenario_identity is not None:
        behavior["scenario_identity"] = scenario_identity
    return SimpleNamespace(
        name="Scenario Character",
        gender="neutral",
        system_prompt="REALITY_SYSTEM_PROMPT",
        description="AUTHORED_DESCRIPTION",
        personality="AUTHORED_PERSONALITY",
        scenario="REALITY_SCENARIO",
        post_history_instructions="REALITY_POST_HISTORY",
        presence_ext={"dream_behavior": behavior},
    )


def _script():
    return {
        "id": "profile_demo",
        "title": "Profile Demo",
        "stages": [{
            "id": "opening",
            "name": "Opening",
            "dramatic_task": "Hold the current stance.",
            "entry_pressure": "The door is closed.",
            "exit_signs": ["the character takes a concrete action"],
            "not_yet_allowed": ["skip the locked door"],
        }],
    }


def _build(character):
    return dump_dream_prompt(build_dream_prompt(
        character=character,
        user_id="scenario_profile_user",
        user_message="continue",
        context_snapshot={
            "recent_reality_context": "REALITY_CONTEXT",
            "entry_reason": "REALITY_ENTRY_REASON",
        },
        dream_history=[],
        local_state={"scene_state": "SCENE_ANCHOR"},
        lore_entries=["DREAM_LORE"],
        body_projection_text="BODY_PROJECTION",
        yexuan_tension=0.8,
        dream_mode="scenario",
        scenario_core={"script_id": "profile_demo", "current_stage_id": "opening"},
    ))


def test_scenario_profile_uses_projection_and_excludes_reality_and_sandbox_layers():
    character = _character()
    before = dict(character.__dict__)
    with patch("core.dream.scenario_loader.load_script", return_value=_script()):
        prompt = _build(character)

    assert "D1S·剧本身份投影" in prompt
    assert "D8S·剧本导演注记" in prompt
    assert "AUTHORED_DESCRIPTION" in prompt
    assert "AUTHORED_PERSONALITY" in prompt
    assert "REALITY_SYSTEM_PROMPT" not in prompt
    assert "REALITY_SCENARIO" not in prompt
    assert "REALITY_POST_HISTORY" not in prompt
    assert "REALITY_CONTEXT" not in prompt
    assert "REALITY_ENTRY_REASON" not in prompt
    assert "DREAM_LORE" not in prompt
    assert "BODY_PROJECTION" not in prompt
    assert "SCENE_ANCHOR" not in prompt
    assert "D2·今晚梦的世界规则" not in prompt
    assert "只有口头威胁、重复警告" in prompt
    assert character.__dict__ == before


def test_scenario_identity_prefers_nested_authored_projection_and_is_bounded():
    character = _character(scenario_identity="  SCENARIO_IDENTITY  ")
    assert scenario_identity_projection(character) == "SCENARIO_IDENTITY"
    assert "REALITY_SYSTEM_PROMPT" not in scenario_identity_projection(character)

    fallback = _character()
    projection = scenario_identity_projection(fallback)
    assert "AUTHORED_DESCRIPTION" in projection
    assert "AUTHORED_PERSONALITY" in projection
    assert len(projection) <= 3600
