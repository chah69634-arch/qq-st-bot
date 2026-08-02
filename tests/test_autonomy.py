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
    def ledger_send(*_args, **_kwargs): raise AssertionError("silent tools must not count as proactive speech")
    monkeypatch.setattr("core.llm_client.chat_turn", chat_turn)
    monkeypatch.setattr(runner, "_execute_tool", execute)
    monkeypatch.setattr("core.scheduler.proactive_ledger.record_send", ledger_send)
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
    exposed = []
    async def chat_turn(_messages, schemas, **_kwargs):
        exposed.append([((schema.get("function") or schema).get("name")) for schema in schemas])
        return next(calls)
    monkeypatch.setattr("core.llm_client.chat_turn", chat_turn)
    run = asyncio.run(runner._run_locked(Job(uid="owner", char_id="char", source="manual"), state, Run(uid="owner", char_id="char", source="manual", job_id="job")))
    assert run.disposition == "talk_soft_blocked_then_canceled"
    assert run.talk_soft_blocked is True
    assert exposed[1] == ["confirm_talk"]


def test_autonomy_tool_policy_rejects_memory_and_unsandboxed_writes():
    from core.autonomy.policy import tool_eligibility
    registry = {
        "water_garden": {"category": "info"},
        "revise_memory": {"category": "info"},
        "desktop_notify": {"category": "desktop"},
    }
    assert tool_eligibility("water_garden", {"enabled": True}, registry=registry, effect="write") == (True, "eligible")
    assert tool_eligibility("revise_memory", {"enabled": True}, registry=registry, effect="write") == (False, "write_not_sandboxed_for_autonomy")
    assert tool_eligibility("desktop_notify", {"enabled": True}, registry=registry, effect="actuate")[0] is False


def test_write_tool_budget_prevents_second_write(sandbox, monkeypatch):
    from core.autonomy import runner, store
    from core.autonomy.models import Job, Run
    state = store.load("owner", "char")
    state["config"].update({"enabled": True, "max_tools": 3, "max_write_tools": 1})
    monkeypatch.setattr(runner.policy, "admission", lambda *args: None)
    monkeypatch.setattr(runner.policy, "allowed_tools", lambda *args: [{"type": "function", "function": {"name": "write_a", "parameters": {}}}, {"type": "function", "function": {"name": "write_b", "parameters": {}}}])
    monkeypatch.setattr(runner.talk_gate, "check", lambda *args, **kwargs: ("hard", "suppressed_unanswered_cap"))
    monkeypatch.setattr(runner, "_is_write_tool", lambda _name: True)
    calls = iter([
        SimpleNamespace(tool_calls=[{"id": "one", "name": "write_a", "arguments": {}}, {"id": "two", "name": "write_b", "arguments": {}}], continuation_items=[], assistant_message={}),
        SimpleNamespace(tool_calls=[], continuation_items=[], assistant_message={}),
    ])
    invoked = []
    async def chat_turn(*_args, **_kwargs): return next(calls)
    async def execute(name, *_args, **_kwargs): invoked.append(name); return "ok", "ok"
    monkeypatch.setattr("core.llm_client.chat_turn", chat_turn)
    monkeypatch.setattr(runner, "_execute_tool", execute)
    run = asyncio.run(runner._run_locked(Job(uid="owner", char_id="char", source="manual"), state, Run(uid="owner", char_id="char", source="manual", job_id="job")))
    assert invoked == ["write_a"]
    assert run.tool_names == ["write_a"]


def test_schedule_window_supports_local_cross_midnight():
    from core.autonomy.runner import _inside_schedule_window
    assert _inside_schedule_window(23, 30, ["22:00", "02:00"])
    assert _inside_schedule_window(1, 30, ["22:00", "02:00"])
    assert not _inside_schedule_window(12, 0, ["22:00", "02:00"])


def test_consecutive_failures_open_circuit_and_success_closes_it(sandbox):
    from core.autonomy import store
    from core.autonomy.models import Job, Run
    job = Job(uid="owner", char_id="char", source="manual")
    state = store.load("owner", "char")
    state["config"].update({"circuit_failure_threshold": 2, "circuit_cooldown_seconds": 60})
    store.save("owner", "char", state)
    for _ in range(2):
        store.enqueue("owner", "char", "manual", dedupe_key=__import__("uuid").uuid4().hex)
        claimed = store.claim_due("owner", "char")
        store.finish(claimed, Run(uid="owner", char_id="char", source="manual", job_id=claimed.id, disposition="llm_failed", finished_at=1))
    state = store.load("owner", "char")
    assert store.circuit_open(state)
    store.enqueue("owner", "char", "manual", dedupe_key=__import__("uuid").uuid4().hex)
    claimed = store.claim_due("owner", "char")
    store.finish(claimed, Run(uid="owner", char_id="char", source="manual", job_id=claimed.id, disposition="completed_no_op", finished_at=1))
    assert not store.circuit_open(store.load("owner", "char"))


def test_admin_enqueue_only_creates_job_not_llm_work(sandbox, monkeypatch):
    import admin.routers.autonomy as api
    monkeypatch.setattr(api, "_scope", lambda: ("owner", "char"))
    calls = []
    async def forbidden(*_args, **_kwargs): calls.append(True); raise AssertionError("LLM must not run in HTTP request")
    monkeypatch.setattr("core.autonomy.runner.run_job", forbidden)
    result = asyncio.run(api.test_enqueue({"source": "schedule"}, auth=None))
    assert result["status"] == "queued" and result["job_id"]
    assert calls == []


def test_admin_config_rejects_bad_timezone(sandbox, monkeypatch):
    import admin.routers.autonomy as api
    monkeypatch.setattr(api, "_scope", lambda: ("owner", "char"))
    import pytest
    with pytest.raises(Exception) as exc:
        asyncio.run(api.patch_config({"schedule": {"timezone": "Not/AZone"}}, auth=None))
    assert "timezone" in str(exc.value)


def test_expired_lease_can_be_reclaimed_but_stale_finisher_cannot_overwrite(sandbox, monkeypatch):
    from core.autonomy import store
    from core.autonomy.models import Run
    job, _ = store.enqueue("owner", "char", "manual", dedupe_key="lease")
    first = store.claim_due("owner", "char")
    state = store.load("owner", "char")
    state["jobs"][0]["lease_until"] = 0
    store.save("owner", "char", state)
    second = store.claim_due("owner", "char")
    assert second.id == first.id and second.lease_token != first.lease_token
    store.finish(first, Run(uid="owner", char_id="char", source="manual", job_id=first.id, disposition="completed_no_op", finished_at=1))
    state = store.load("owner", "char")
    assert state["jobs"][0]["status"] == "processing"
    assert state.get("sources", {}).get("manual", {}).get("last_evaluated_at") is None


def test_talk_does_not_enter_turn_sink_without_a_delivery_channel(sandbox, monkeypatch):
    from core.autonomy import talk_gate
    monkeypatch.setattr(talk_gate, "check", lambda *_args, **_kwargs: ("allow", "ok"))
    monkeypatch.setattr("core.pipeline_registry.get", lambda: object())
    monkeypatch.setattr("channels.registry.get_active", lambda: [])
    invoked = []
    async def forbidden(**_kwargs): invoked.append(True)
    monkeypatch.setattr("core.turn_sink.record_assistant_turn", forbidden)
    sent, reason = asyncio.run(talk_gate.send("owner", "char", "可以聊一句。", source="manual", run_id="run"))
    assert not sent and reason == "no_delivery_channel"
    assert invoked == []


def test_temporary_retry_is_durably_backed_off(sandbox):
    from core.autonomy import store
    from core.autonomy.models import Run
    store.enqueue("owner", "char", "schedule", dedupe_key="retry")
    job = store.claim_due("owner", "char")
    store.finish(job, Run(uid="owner", char_id="char", source="schedule", job_id=job.id, disposition="blocked_dream", finished_at=1), retry=True)
    state = store.load("owner", "char")
    assert state["jobs"][0]["next_attempt_at"] > 0
    assert store.claim_due("owner", "char") is None


def test_successful_talk_uses_turn_sink_then_records_shared_ledger(sandbox, monkeypatch):
    from core.autonomy import talk_gate
    monkeypatch.setattr(talk_gate, "check", lambda *_args, **_kwargs: ("allow", "ok"))
    monkeypatch.setattr("core.pipeline_registry.get", lambda: object())
    monkeypatch.setattr("channels.registry.get_active", lambda: [object()])
    monkeypatch.setattr("core.response_processor.strip_render_tags", lambda text: text)
    monkeypatch.setattr("core.reality_output_scrubber.scrub_reality_output_text", lambda text: text)
    order = []
    async def turn_sink(**kwargs):
        order.append(("sink", kwargs)); return SimpleNamespace(fanout_targets=["desktop"])
    def ledger(*args, **kwargs): order.append(("ledger", kwargs))
    monkeypatch.setattr("core.turn_sink.record_assistant_turn", turn_sink)
    monkeypatch.setattr("core.scheduler.proactive_ledger.record_send", ledger)
    sent, reason = asyncio.run(talk_gate.send("owner", "char", "可以聊一句。", source="manual", run_id="run"))
    assert sent and reason == "sent"
    assert [item[0] for item in order] == ["sink", "ledger"]
    assert order[1][1]["uid"] == "owner"
