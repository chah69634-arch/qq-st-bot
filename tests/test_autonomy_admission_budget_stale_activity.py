"""Brief 224: admission-only counters, zero-talk budget bypass, stale activity TTL."""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest


def _admission_ready(monkeypatch):
    from core.dream.dream_state import DreamGuardStatus

    monkeypatch.setattr("core.character_loader.is_proactive_disabled", lambda: False)
    monkeypatch.setattr(
        "core.dream.dream_state.get_reality_guard_status",
        lambda _uid: DreamGuardStatus.ALLOW,
    )
    monkeypatch.setattr(
        "core.scheduler.state_machine.get_state",
        lambda _uid: __import__(
            "core.scheduler.state_machine", fromlist=["TriggerState"]
        ).TriggerState.QUIET,
    )
    monkeypatch.setattr(
        "core.conversation_gate.conversation_lock",
        lambda _uid: SimpleNamespace(locked=lambda: False),
    )
    monkeypatch.setattr("core.message_queue.active_sessions", lambda: set())
    monkeypatch.setattr("core.message_queue.queue_size", lambda _uid: 0)
    monkeypatch.setattr("core.coplay.session.is_active", lambda *_a, **_k: False)


def test_admission_only_finish_does_not_burn_budget_or_cooldown(sandbox):
    from core.autonomy.models import Job, Run
    from core.autonomy import store

    state = store.load("owner", "char")
    state["config"]["enabled"] = True
    state["daily"] = {"day": "2026-08-27", "evaluations": 0, "tools": 0, "talks": 0}
    state["sources"] = {"scheduler": {"last_evaluated_at": 0.0}}
    store.save("owner", "char", state)

    job = Job(
        uid="owner",
        char_id="char",
        source="autonomy",
        signal_sources=["scheduler", "topic_followup"],
        status="processing",
        lease_token="tok",
        lease_until=time.time() + 60,
    )
    state = store.load("owner", "char")
    state["jobs"] = [job.to_dict()]
    store.save("owner", "char", state)

    run = Run(
        uid="owner",
        char_id="char",
        source="autonomy",
        job_id=job.id,
        disposition="blocked_user_active",
        evaluation_status="admission_blocked",
        finished_at=time.time(),
    )
    store.finish(job, run)

    state = store.load("owner", "char")
    assert state["daily"]["evaluations"] == 0
    assert state["daily"]["talks"] == 0
    scheduler = state["sources"]["scheduler"]
    assert float(scheduler.get("last_evaluated_at") or 0) == 0.0
    assert float(scheduler.get("last_attempt_at") or 0) > 0
    assert any(r.get("disposition") == "blocked_user_active" for r in state["runs"])


def test_zero_talk_budget_bypass_and_effective_state(sandbox, monkeypatch):
    from core.autonomy import effective_state, policy, store

    _admission_ready(monkeypatch)
    monkeypatch.setattr("core.activity.store.find_active_session", lambda *_a, **_k: None)

    state = store.load("owner", "char")
    state["config"].update(
        {"enabled": True, "min_interval_seconds": 0, "daily_evaluation_budget": 2}
    )
    state["sources"] = {}
    state["daily"] = {"day": "2026-08-27", "evaluations": 9, "tools": 0, "talks": 0}
    monkeypatch.setattr("core.autonomy.store.roll_daily", lambda _state: None)
    assert policy.admission("owner", "char", state) is None

    store.save("owner", "char", state)
    monkeypatch.setattr(
        "core.autonomy.effective_state.scheduler_enabled", lambda _cfg=None: True
    )
    monkeypatch.setattr(
        "core.autonomy.effective_state._scheduler_runtime",
        lambda: {"available": True, "running": True},
    )
    monkeypatch.setattr("core.autonomy.talk_gate.check", lambda _uid: ("allow", ""))
    monkeypatch.setattr("core.pipeline_registry.get", lambda: object())
    monkeypatch.setattr("channels.registry.get_active", lambda: ["desktop"])

    payload = effective_state.build_effective_state("owner", "char")
    budget = payload["daily_evaluation_budget"]
    assert budget["blocked"] is False
    assert budget["zero_talk_bypass"] is True
    assert payload["proactive"]["can_evaluate"] is True


def test_stale_dream_seed_lazy_expires_for_find_active(sandbox):
    from core.activity import store
    from core.activity.session import ActivitySession

    old = datetime.now(timezone.utc) - timedelta(hours=30)
    session = ActivitySession(
        session_id="staleseed001",
        uid="owner",
        char_id="char",
        activity_type="dream_seed",
        status="active",
        state={"started_at": old.timestamp()},
        created_at=old.isoformat(),
        updated_at=old.isoformat(),
    )
    store.save_session(session)
    assert store.find_active_session("char", "owner", "dream_seed") is None
    loaded = store.load_session("char", "owner", "dream_seed", "staleseed001")
    assert loaded is not None
    assert loaded.status == "closed"
    assert loaded.state.get("close_reason") == "stale_ttl"


def test_fresh_dream_seed_still_blocks_admission(sandbox, monkeypatch):
    from core.activity import store as activity_store
    from core.autonomy import policy, store

    _admission_ready(monkeypatch)
    session = activity_store.create_session(
        uid="owner",
        char_id="char",
        activity_type="dream_seed",
        initial_state={"started_at": time.time()},
    )
    assert activity_store.find_active_session("char", "owner", "dream_seed") is not None

    state = store.load("owner", "char")
    state["config"].update({"enabled": True, "min_interval_seconds": 0, "daily_evaluation_budget": 12})
    state["sources"] = {}
    state["daily"] = {"day": "2026-08-27", "evaluations": 0, "tools": 0, "talks": 0}
    monkeypatch.setattr("core.autonomy.store.roll_daily", lambda _state: None)
    assert policy.admission("owner", "char", state) == "blocked_user_active"
    # cleanup for other tests in same sandbox root
    activity_store.close_session("char", "owner", "dream_seed", session.session_id)
