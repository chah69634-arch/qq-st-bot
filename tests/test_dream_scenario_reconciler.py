from __future__ import annotations
from tests.fixtures.public_assets import TEST_CHAR_ID

import asyncio
from unittest.mock import AsyncMock, patch


def _script() -> dict:
    return {
        "id": "reconcile_demo",
        "title": "Reconcile Demo",
        "stages": [
            {"id": "arrival", "name": "Arrival", "dramatic_task": "A", "entry_pressure": "P", "exit_signs": ["E"]},
            {"id": "next", "name": "Next", "dramatic_task": "B", "entry_pressure": "Q", "exit_signs": ["F"]},
        ],
    }


def _request(uid: str, version: int) -> dict:
    return {
        "uid": uid,
        "dream_id": "dream-reconcile",
        "char_id": TEST_CHAR_ID,
        "turn_index": 0,
        "assistant_turn_id": "dream-reconcile:assistant:1",
        "state_version": version,
        "from_stage_id": "arrival",
        "current_stage": _script()["stages"][0],
        "next_stage": _script()["stages"][1],
        "completion_signals": [],
        "dialogue": [{"role": "user", "text": "visible"}],
        "trigger": "control_missing",
    }


def test_reconciler_parser_is_closed_enum():
    from core.dream.scenario_reconciler import parse_decision

    assert parse_decision('{"decision":"stay"}') == "stay"
    assert parse_decision('{"decision":"advance_next","next_stage_id":"skip"}') == "advance_next"
    assert parse_decision('{"decision":"jump"}') == "uncertain"
    assert parse_decision("not json") == "uncertain"


def test_reconciler_advances_only_adjacent_stage_with_cas(sandbox, monkeypatch):
    from core.dream.dream_state import DreamStatus, read_state, write_state
    from core.dream.scenario_reconciler import _run

    uid = "reconcile_apply"
    state = {
        "user_id": uid,
        "status": DreamStatus.DREAM_ACTIVE.value,
        "dream_mode": "scenario",
        "dream_id": "dream-reconcile",
        "scenario_core": {
            "script_id": "reconcile_demo",
            "current_stage_id": "arrival",
        },
        "last_assistant_turn_id": "dream-reconcile:assistant:1",
    }
    write_state(uid, state)
    version = read_state(uid)["state_version"]
    monkeypatch.setattr("core.dream.scenario_loader.load_script", lambda _id: _script())
    monkeypatch.setattr("core.dream.scenario_loader.get_next_stage", lambda script, _id: script["stages"][1])

    async def run():
        with patch("core.llm_client.chat", new=AsyncMock(return_value='{"decision":"advance_next"}')):
            await _run(_request(uid, version))

    asyncio.run(run())
    updated = read_state(uid)
    assert updated["scenario_core"]["current_stage_id"] == "next"
    assert updated["state_version"] > version


def test_reconciler_stale_version_does_not_call_llm(sandbox, monkeypatch):
    from core.dream.dream_state import DreamStatus, read_state, write_state
    from core.dream.scenario_reconciler import _run

    uid = "reconcile_stale"
    write_state(uid, {
        "user_id": uid,
        "status": DreamStatus.DREAM_ACTIVE.value,
        "dream_mode": "scenario",
        "dream_id": "dream-reconcile",
        "scenario_core": {"script_id": "reconcile_demo", "current_stage_id": "arrival"},
        "last_assistant_turn_id": "dream-reconcile:assistant:1",
    })
    captured = read_state(uid)["state_version"]
    current = read_state(uid)
    current["last_assistant_turn_id"] = "dream-reconcile:assistant:2"
    write_state(uid, current)
    llm = AsyncMock(return_value='{"decision":"advance_next"}')

    async def run():
        with patch("core.llm_client.chat", new=llm):
            await _run(_request(uid, captured))

    asyncio.run(run())
    llm.assert_not_awaited()
    assert read_state(uid)["scenario_core"]["current_stage_id"] == "arrival"
