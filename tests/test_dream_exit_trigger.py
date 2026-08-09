from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import time

import pytest


def _write_state(*, mode="sandbox", greeted=None, exited_hours_ago=0.0):
    from core.dream.dream_state import DreamStatus, write_state

    state = {
        "status": DreamStatus.REALITY_AFTERGLOW.value,
        "char_id": "dreamer",
        "last_dream_id": "dream-1",
        "last_exit_type": "soft",
        "last_dream_mode": mode,
        "last_exited_at": time.time() - exited_hours_ago * 3600,
    }
    if greeted is not None:
        state["last_greeted_dream_id"] = greeted
    write_state("owner", state)


def _write_afterglow(*, age_hours=1.0, tone="comfort"):
    from core.memory.user_hidden_state import AfterglowResidueInput
    from core.memory.user_hidden_state_store import save_afterglow_residue

    created_at = (datetime.now(timezone.utc) - timedelta(hours=age_hours)).isoformat()
    save_afterglow_residue(
        "owner",
        AfterglowResidueInput(emotional_tags=["warm"], tone=tone, age_hours=age_hours),
        created_at,
        char_id="dreamer",
    )


def test_propose_fresh_afterglow_and_dream_char_scope(sandbox):
    from core.scheduler.triggers import dream_exit

    _write_state(exited_hours_ago=1.1)
    _write_afterglow()

    proposal = dream_exit.propose({"uid": "owner", "char_id": "other-active"})

    assert proposal is not None
    assert proposal.trigger_name == "dream_exit"
    assert proposal.char_id == "dreamer"


@pytest.mark.asyncio
async def test_one_dream_once_and_successful_execute_marks_state(sandbox, monkeypatch):
    from core.dream.dream_state import read_state
    from core.scheduler.triggers import dream_exit
    import core.scheduler.execution as execution

    _write_state(greeted="dream-1", exited_hours_ago=1.1)
    _write_afterglow()
    assert dream_exit.propose({"uid": "owner"}) is None

    _write_state(exited_hours_ago=1.1)
    proposal = dream_exit.propose({"uid": "owner"})

    async def fake_execute_prompt(**kwargs):
        assert kwargs["char_id"] == "dreamer"
        kwargs["after_send"]()
        return SimpleNamespace(sent=True)

    monkeypatch.setattr(execution, "execute_prompt", fake_execute_prompt)
    result = await proposal.execute(dry_run=False)

    assert result.sent is True
    assert read_state("owner")["last_greeted_dream_id"] == "dream-1"


def test_quiet_only_is_filtered_while_chatting(sandbox, monkeypatch):
    from core.scheduler import gating
    from core.scheduler.state_machine import TriggerState
    from core.scheduler.triggers import dream_exit

    _write_state(exited_hours_ago=1.1)
    _write_afterglow()
    proposal = dream_exit.propose({"uid": "owner"})

    monkeypatch.setattr(gating, "get_current_state", lambda uid: TriggerState.CHATTING)
    monkeypatch.setattr(gating, "is_trigger_ready", lambda name, **kwargs: True)

    assert gating.collect_and_decide("owner", [proposal]) is None
    from core.dream.exit_observability import get_record

    record = get_record("dream-1", char_id="dreamer")
    assert record is not None
    assert record["lifecycle"] == "blocked"
    assert record["reason_code"] == "not_quiet"


def test_no_afterglow_waits_but_scenario_and_expired_degrade_to_neutral(sandbox):
    from core.dream.dream_state import read_state
    from core.scheduler.triggers import dream_exit

    _write_state()
    assert dream_exit.propose({"uid": "owner"}) is None

    _write_state(mode="scenario")
    scenario = dream_exit.propose({"uid": "owner"})
    assert scenario is not None
    scenario_state = read_state("owner")
    assert dream_exit._resolve_timing(
        "owner", char_id="dreamer", state=scenario_state, mode="scenario"
    )[0] == "neutral"

    _write_state(exited_hours_ago=9.0)
    _write_afterglow(age_hours=9.0)
    assert dream_exit.propose({"uid": "owner"}) is not None


def test_previous_dream_afterglow_is_not_reused_while_new_summary_is_pending(sandbox):
    from core.scheduler.triggers import dream_exit

    _write_afterglow(age_hours=1.0)
    _write_state()

    assert dream_exit.propose({"uid": "owner"}) is None


@pytest.mark.asyncio
async def test_execute_prompt_passes_explicit_char_to_pipeline_send(monkeypatch):
    from core.scheduler import execution, loop

    calls = []

    async def fake_send(prompt, **kwargs):
        calls.append(kwargs)
        return "sent"

    monkeypatch.setattr(loop, "_pipeline_send", fake_send)
    monkeypatch.setattr(loop, "_mark", lambda *args, **kwargs: None)

    result = await execution.execute_prompt(
        trigger_name="dream_exit",
        prompt_factory=lambda: "prompt",
        dry_run=False,
        char_id="dreamer",
    )

    assert result.sent is True
    assert calls[0]["char_id"] == "dreamer"


def test_prompt_tone_and_clarity_mapping():
    from core.scheduler.triggers.dream_exit import _build_dream_exit_prompt

    stress = _build_dream_exit_prompt("stress", "soft", False, char_name="甲")
    hard = _build_dream_exit_prompt("comfort", "hard_exit", False, char_name="甲")
    comfort = _build_dream_exit_prompt("comfort", "soft", False, char_name="甲")
    calm = _build_dream_exit_prompt("calm", "soft", False, char_name="甲")
    fuzzy = _build_dream_exit_prompt("calm", "soft", False, age_hours=3.0, char_name="甲")
    neutral = _build_dream_exit_prompt("neutral", "soft", True, char_name="甲")

    assert "先确认她好不好" in stress
    assert "先确认她好不好" in hard
    assert "温暖松弛" in comfort
    assert "平和自然" in calm
    assert "别编造具体情节" in fuzzy
    assert "不要引用梦里的具体内容" in neutral
