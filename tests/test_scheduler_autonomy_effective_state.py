from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace


def test_global_scheduler_and_source_switches_reach_signal_producer(sandbox, monkeypatch):
    import core.config_loader as loader
    from core.autonomy.signal_adapters import emit_trigger_signal, routine_trigger_enabled

    cfg = {"scheduler": {"enabled": True, "morning_greeting": False}}
    monkeypatch.setattr(loader, "get_config", lambda: cfg)
    assert routine_trigger_enabled("morning_greeting") is False
    queued, reason = emit_trigger_signal("owner", "char", "morning_greeting")
    assert not queued and reason == "disabled"
    cfg["scheduler"]["enabled"] = False
    assert routine_trigger_enabled("morning_greeting") is False


def test_talk_switch_reaches_autonomy_runtime_schema(sandbox, monkeypatch):
    from core.autonomy import runner, store
    from core.autonomy.models import Job, Run

    _admission_ready(monkeypatch)
    state = store.load("owner", "char")
    state["config"].update({"enabled": True, "talk_enabled": False, "max_steps": 1})
    monkeypatch.setattr(runner.policy, "allowed_tools", lambda *_args: [])
    monkeypatch.setattr(runner.talk_gate, "check", lambda *_args, **_kwargs: ("allow", "ok"))
    monkeypatch.setattr(runner, "_runtime_tools", lambda *_args: ([], None))
    seen = []

    async def chat_turn(_messages, schemas, **_kwargs):
        seen.append({(item.get("function") or item).get("name") for item in schemas})
        return SimpleNamespace(tool_calls=[], continuation_items=[], assistant_message={})

    monkeypatch.setattr("core.llm_client.chat_turn", chat_turn)
    run = asyncio.run(runner._run_locked(
        Job(uid="owner", char_id="char", source="manual"),
        state,
        Run(uid="owner", char_id="char", source="manual", job_id="job"),
    ))
    # talk_enabled=false is an effective runtime gate; the runner may still
    # perform a model step for tools, but it must not expose talk_owner.
    assert all("talk_owner" not in names for names in seen)
    assert any(event.get("status") == "talk_unavailable" and event.get("reason") == "talk_disabled" for event in run.events)


def _admission_ready(monkeypatch):
    from core.dream.dream_state import DreamGuardStatus

    monkeypatch.setattr("core.character_loader.is_proactive_disabled", lambda: False)
    monkeypatch.setattr("core.dream.dream_state.get_reality_guard_status", lambda _uid: DreamGuardStatus.ALLOW)
    monkeypatch.setattr("core.scheduler.state_machine.get_state", lambda _uid: __import__("core.scheduler.state_machine", fromlist=["TriggerState"]).TriggerState.QUIET)
    monkeypatch.setattr("core.conversation_gate.conversation_lock", lambda _uid: SimpleNamespace(locked=lambda: False))
    monkeypatch.setattr("core.message_queue.active_sessions", lambda: set())
    monkeypatch.setattr("core.message_queue.queue_size", lambda _uid: 0)
    monkeypatch.setattr("core.activity.store.find_active_session", lambda *_args, **_kwargs: False)
    monkeypatch.setattr("core.coplay.session.is_active", lambda *_args, **_kwargs: False)


def test_cooldown_and_daily_budget_reach_admission(sandbox, monkeypatch):
    from core.autonomy import policy, store

    _admission_ready(monkeypatch)
    state = store.load("owner", "char")
    state["config"].update({"enabled": True, "min_interval_seconds": 900, "daily_evaluation_budget": 2})
    state["sources"] = {"interval": {"last_evaluated_at": time.time()}}
    assert policy.admission("owner", "char", state) == "duplicate"
    state["sources"] = {}
    state["daily"] = {"day": "", "evaluations": 2, "tools": 0, "talks": 0}
    monkeypatch.setattr("core.autonomy.store.roll_daily", lambda _state: None)
    assert policy.admission("owner", "char", state) == "suppressed_daily_budget"


def test_self_capability_override_reaches_runner_tick(sandbox):
    from core.autonomy import effective_state, store
    from core.self_management import registry
    from core.self_management.service import user_grant
    from core.self_management import store as capability_store

    state = store.load("owner", "char")
    state["config"]["enabled"] = True
    store.save("owner", "char", state)
    assert user_grant("owner", "char", capability_id=registry.AUTONOMY_ENABLED, allowed=True, mutable_by_agent=True, constraints={}, reason="test").ok
    capability = capability_store.load("owner", "char")
    capability["agent_state"][registry.AUTONOMY_ENABLED] = False
    capability_store.save("owner", "char", capability)
    assert effective_state.autonomy_enabled("owner", "char", state) is False
    asyncio.run(__import__("core.autonomy.runner", fromlist=["tick"]).tick("owner", "char"))
    assert store.load("owner", "char")["jobs"] == []


def test_effective_state_contract_reports_reason_and_trigger_lifecycles(sandbox, monkeypatch):
    import admin.routers.autonomy as api
    monkeypatch.setattr(api, "_scope", lambda: ("owner", "char"))
    data = asyncio.run(api.effective_state(auth=None))
    assert data["contract_version"] == "scheduler-autonomy-effective-state.v1"
    assert data["proactive"]["state"] in {"disabled", "unavailable", "enabled", "blocked", "cooled_down", "queued", "running"}
    rows = {row["name"]: row for row in data["trigger_sources"]}
    assert rows["morning_greeting"]["lifecycle"] == "migrated"
    assert rows["log_maintenance"]["lifecycle"] == "maintenance-only"
    assert rows["scheduler_pipeline_send"]["lifecycle"] == "retired"
    assert {"configured_value", "effective_value", "override_source", "restart_required", "runtime_consumer"} <= set(rows["morning_greeting"])
