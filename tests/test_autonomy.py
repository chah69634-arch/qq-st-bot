from __future__ import annotations

import asyncio
from types import SimpleNamespace


def test_autonomy_state_is_durable_and_manual_enqueue_is_not_execution(sandbox):
    from core.autonomy import store
    job, status = store.enqueue("owner", "char", "manual", dedupe_key="test-job")
    assert status == "queued" and job is not None
    state = store.load("owner", "char")
    assert state["jobs"][0]["status"] == "pending"
    assert state["runs"] == []


def test_autonomy_origin_is_explicit_and_fail_closed_for_unknown(sandbox):
    from core import tool_dispatcher
    assert "autonomy_loop" in tool_dispatcher._EXECUTE_ALLOWED_ORIGINS
    result = asyncio.run(tool_dispatcher.execute("get_time", {}, "owner", "owner", False, object(), origin="unknown_autonomy", char_id="char"))
    assert result == (None, None)


def test_two_unanswered_messages_hide_talk_and_real_user_message_resets(sandbox, monkeypatch):
    from core.scheduler import proactive_ledger as ledger
    monkeypatch.setattr(ledger, "_cfg", lambda: {"owner_id": "owner", "global_proactive_min_gap_seconds": 1, "max_daily_proactive": 99})
    ledger.record_send("scheduler", uid="owner")
    ledger.record_send("wake", uid="owner")
    assert ledger.continuity_status("owner")["consecutive_unanswered_talks"] == 2
    allowed, reason = ledger.can_send("autonomy", uid="owner")
    assert not allowed and reason == "unanswered_cap"
    ledger.record_user_message("owner")
    assert ledger.continuity_status("owner")["consecutive_unanswered_talks"] == 0


def test_autonomy_tool_schema_never_contains_talk_when_cap_reached(sandbox, monkeypatch):
    from core.autonomy import talk_gate
    monkeypatch.setattr("core.scheduler.proactive_ledger.continuity_status", lambda uid: {"consecutive_unanswered_talks": 2})
    mode, reason = talk_gate.check("owner")
    assert mode == "hard" and reason == "suppressed_unanswered_cap"


def test_tools_only_run_never_imports_or_calls_turn_sink(sandbox, monkeypatch):
    from core.autonomy import runner, store
    from core.autonomy.models import Job
    state = store.load("owner", "char"); state["config"]["enabled"] = True
    monkeypatch.setattr(runner.policy, "admission", lambda *args: None)
    monkeypatch.setattr(runner.policy, "allowed_tools", lambda *args: [{"type": "function", "function": {"name": "safe_tool", "parameters": {}}}])
    monkeypatch.setattr(runner.talk_gate, "check", lambda *args, **kwargs: ("hard", "suppressed_unanswered_cap"))
    calls = iter([
        SimpleNamespace(tool_calls=[{"id": "one", "name": "safe_tool", "arguments": {}}], continuation_items=[], assistant_message={}),
        SimpleNamespace(tool_calls=[], continuation_items=[], assistant_message={}),
    ])
    async def chat_turn(*_args, **_kwargs): return next(calls)
    async def execute(*_args, **_kwargs): return "ok", "ok"
    monkeypatch.setattr("core.llm_client.chat_turn", chat_turn)
    monkeypatch.setattr(runner, "_execute_tool", execute)
    run = asyncio.run(runner._run_locked(Job(uid="owner", char_id="char", source="manual"), state, runner.Run(uid="owner", char_id="char", source="manual", job_id="job")))
    assert run.disposition == "completed_tools_only"
    assert run.talk_sent is False


def test_soft_block_allows_only_one_confirm_decision(sandbox, monkeypatch):
    from core.autonomy import runner, store
    from core.autonomy.models import Job, Run
    state = store.load("owner", "char"); state["config"]["enabled"] = True
    monkeypatch.setattr(runner.policy, "admission", lambda *args: None)
    monkeypatch.setattr(runner.policy, "allowed_tools", lambda *args: [])
    modes = iter([("soft", "gap_not_elapsed"), ("soft", "gap_not_elapsed")])
    monkeypatch.setattr(runner.talk_gate, "check", lambda *args, **kwargs: next(modes))
    calls = iter([
        SimpleNamespace(tool_calls=[{"id": "talk", "name": "talk_owner", "arguments": {"text": "hi", "reason": "test"}}], continuation_items=[], assistant_message={}),
        SimpleNamespace(tool_calls=[{"id": "confirm", "name": "confirm_talk", "arguments": {"action": "cancel"}}], continuation_items=[], assistant_message={}),
    ])
    async def chat_turn(*_args, **_kwargs): return next(calls)
    monkeypatch.setattr("core.llm_client.chat_turn", chat_turn)
    run = asyncio.run(runner._run_locked(Job(uid="owner", char_id="char", source="manual"), state, Run(uid="owner", char_id="char", source="manual", job_id="job")))
    assert run.disposition == "talk_soft_blocked_then_canceled"
    assert run.talk_soft_blocked is True
