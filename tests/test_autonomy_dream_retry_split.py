from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor

import pytest


def _signal(source: str, signal_id: str, *, expiry: float):
    from core.autonomy.models import Signal

    return Signal(
        source=source,
        evidence=[{"fact": f"{source}_fact"}],
        reason=f"A bounded {source} fact is available.",
        expiry=expiry,
        priority=0.9 if source == "hr_critical" else 0.3,
        action_mode="reflect",
        id=signal_id,
    )


def _claimed_job(signals, *, ttl_seconds: int = 600):
    from core.autonomy import store

    job, status = store.enqueue_opportunity(
        "owner",
        "char",
        signals,
        dedupe_key=f"parent:{signals[0].signal_id}",
        ttl_seconds=ttl_seconds,
    )
    assert status == "queued" and job is not None
    claimed = store.claim_due("owner", "char")
    assert claimed is not None
    return claimed


def _blocked_run(job, *, run_id: str = "blocked-run"):
    from core.autonomy.models import Run

    return Run(
        uid=job.uid,
        char_id=job.char_id,
        source=job.source,
        job_id=job.id,
        id=run_id,
        disposition="blocked_dream",
        finished_at=time.time(),
        opportunity_id=job.opportunity["id"],
        signal_count=len(job.opportunity["signals"]),
        evaluation_status="blocked_or_failed",
    )


def test_pure_wake_dream_block_is_terminal_without_child(sandbox):
    from core.autonomy import store

    now = time.time()
    parent = _claimed_job([_signal("desktop_wake", "wake", expiry=now + 300)])
    child = store.finish_dream_blocked_with_signal_split(
        parent, _blocked_run(parent), now=now
    )

    assert child is None
    state = store.load("owner", "char")
    assert len(state["jobs"]) == 1
    assert state["jobs"][0]["status"] == "done"
    assert state["jobs"][0]["next_attempt_at"] == 0
    assert state["runs"][0]["events"] == [{
        "status": "signal_terminal_one_shot",
        "signal_id": "wake",
        "source": "desktop_wake",
        "outcome": "not_replayed",
    }]


def test_mixed_wake_and_critical_signal_creates_one_bounded_child(sandbox):
    from core.autonomy import store

    now = time.time()
    parent = _claimed_job([
        _signal("desktop_wake", "wake", expiry=now + 500),
        _signal("hr_critical", "hr", expiry=now + 120),
    ])
    run = _blocked_run(parent)
    child = store.finish_dream_blocked_with_signal_split(parent, run, now=now)

    assert child is not None
    assert child.retry_parent_job_id == parent.id
    assert child.retry_parent_run_id == run.id
    assert child.ttl_seconds <= 120
    assert child.signal_sources == ["hr_critical"]
    assert [item["source"] for item in child.opportunity["signals"]] == [
        "hr_critical"
    ]

    state = store.load("owner", "char")
    assert [job["status"] for job in state["jobs"]] == ["done", "pending"]
    events = state["runs"][0]["events"]
    assert any(event.get("outcome") == "not_replayed" for event in events)
    queued = next(event for event in events if event["status"] == "dream_retry_child_queued")
    assert queued["child_job_id"] == child.id
    assert queued["signal_ids"] == ["hr"]

    state["jobs"][1]["next_attempt_at"] = 0
    assert store.save("owner", "char", state)
    claimed_child = store.claim_due("owner", "char")
    assert claimed_child is not None and claimed_child.id == child.id


def test_mixed_retry_merges_all_valid_non_wake_signals_into_one_child(sandbox):
    from core.autonomy import store

    now = time.time()
    parent = _claimed_job([
        _signal("desktop_wake", "wake", expiry=now + 500),
        _signal("scheduler", "schedule", expiry=now + 240),
        _signal("sensor", "sensor", expiry=now + 180),
    ])

    child = store.finish_dream_blocked_with_signal_split(
        parent, _blocked_run(parent), now=now
    )

    assert child is not None
    assert child.signal_sources == ["scheduler", "sensor"]
    assert len(child.opportunity["signals"]) == 2
    assert len(store.load("owner", "char")["jobs"]) == 2


@pytest.mark.parametrize("all_expired", [False, True])
def test_expired_non_wake_signals_are_terminal_and_not_retried(
    sandbox, all_expired
):
    from core.autonomy import store

    created_at = time.time()
    blocked_at = created_at + 2
    signals = [
        _signal("desktop_wake", "wake", expiry=created_at + 500),
        _signal("sensor", "expired-sensor", expiry=created_at + 1),
    ]
    if not all_expired:
        signals.append(
            _signal("scheduler", "valid-schedule", expiry=created_at + 180)
        )
    parent = _claimed_job(signals)

    child = store.finish_dream_blocked_with_signal_split(
        parent, _blocked_run(parent), now=blocked_at
    )

    if all_expired:
        assert child is None
        assert len(store.load("owner", "char")["jobs"]) == 1
    else:
        assert child is not None
        assert child.signal_sources == ["scheduler"]
    events = store.load("owner", "char")["runs"][0]["events"]
    expired = next(event for event in events if event.get("signal_id") == "expired-sensor")
    assert expired["status"] == "signal_terminal_expired"
    assert expired["outcome"] == "expired"


def test_split_is_idempotent_and_stale_lease_cannot_overwrite_reclaim(sandbox):
    from core.autonomy import store

    now = time.time()
    parent = _claimed_job([
        _signal("desktop_wake", "wake", expiry=now + 500),
        _signal("sensor", "sensor", expiry=now + 180),
    ])
    run = _blocked_run(parent)
    first_child = store.finish_dream_blocked_with_signal_split(parent, run, now=now)
    assert first_child is not None
    assert store.finish_dream_blocked_with_signal_split(parent, run, now=now) is None
    state = store.load("owner", "char")
    assert len(state["jobs"]) == 2
    assert len(state["runs"]) == 1

    state = store.load("owner", "char")
    state["jobs"][1]["next_attempt_at"] = 0
    assert store.save("owner", "char", state)
    first_claim = store.claim_due("owner", "char")
    state = store.load("owner", "char")
    child_raw = next(job for job in state["jobs"] if job["id"] == first_child.id)
    child_raw["lease_until"] = 0
    assert store.save("owner", "char", state)
    second_claim = store.claim_due("owner", "char")
    assert second_claim.lease_token != first_claim.lease_token
    store.finish(first_claim, _blocked_run(first_claim, run_id="stale"), retry=True)
    persisted = next(
        job for job in store.load("owner", "char")["jobs"]
        if job["id"] == first_child.id
    )
    assert persisted["status"] == "processing"
    assert persisted["lease_token"] == second_claim.lease_token


def test_concurrent_signal_enqueue_and_config_replace_preserve_split_state(sandbox):
    from core.autonomy import store

    now = time.time()
    parent = _claimed_job([
        _signal("desktop_wake", "wake", expiry=now + 500),
        _signal("sensor", "sensor", expiry=now + 180),
    ])
    run = _blocked_run(parent)
    new_signal = _signal("scheduler", "concurrent", expiry=now + 300)
    config = store.load("owner", "char")["config"]
    config["talk_enabled"] = False

    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [
            pool.submit(
                store.finish_dream_blocked_with_signal_split,
                parent,
                run,
                now=now,
            ),
            pool.submit(
                store.enqueue_signal,
                "owner",
                "char",
                new_signal,
                dedupe_key="concurrent-signal",
            ),
            pool.submit(store.replace_config, "owner", "char", config),
        ]
        results = [future.result(timeout=5) for future in futures]

    assert results[0] is not None
    assert results[1] == (True, "queued")
    assert results[2] is True
    state = store.load("owner", "char")
    assert len(state["jobs"]) == 2
    assert len(state["runs"]) == 1
    assert state["pending_signals"][0]["signal"]["signal_id"] == "concurrent"
    assert state["config"]["talk_enabled"] is False


@pytest.mark.asyncio
async def test_tick_splits_mixed_dream_block_and_observability_links_child(
    sandbox, monkeypatch
):
    from admin.routers import autonomy as autonomy_router
    from core.autonomy import runner, store
    from core.autonomy.models import Disposition

    now = time.time()
    parent = _claimed_job([
        _signal("desktop_wake", "wake", expiry=now + 500),
        _signal("hr_critical", "hr", expiry=now + 180),
    ])
    # Let tick claim the parent itself.
    state = store.load("owner", "char")
    state["jobs"][0].update({
        "status": "pending",
        "lease_until": 0,
        "lease_token": "",
        "next_attempt_at": 0,
    })
    state["config"]["enabled"] = True
    assert store.save("owner", "char", state)
    monkeypatch.setattr(
        "core.self_management.policy.autonomy_enabled", lambda *_args: True
    )
    monkeypatch.setattr(
        "core.scheduler.triggers.watch.get_last_heart_rate_event", lambda: None
    )
    monkeypatch.setattr(
        "core.scheduler.last_mentioned.recall_last_mentioned",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        "core.memory.episodic_memory._load_memories", lambda *_args, **_kwargs: []
    )
    monkeypatch.setattr(runner, "_schedule_due", lambda *_args, **_kwargs: False)

    async def blocked(job):
        run = _blocked_run(job, run_id="tick-blocked")
        run.disposition = Disposition.BLOCKED_DREAM.value
        return run

    monkeypatch.setattr(runner, "run_job", blocked)
    await runner.tick("owner", "char")

    monkeypatch.setattr(autonomy_router, "_scope", lambda: ("owner", "char"))
    observed = await autonomy_router.opportunities(limit=20, auth=object())
    child = next(
        entry for entry in observed["entries"]
        if entry["kind"] == "opportunity" and entry["retry_parent_job_id"]
    )
    parent_run = next(
        entry for entry in observed["entries"]
        if entry["kind"] == "run" and entry["run_id"] == "tick-blocked"
    )
    assert child["retry_parent_job_id"] == parent.id
    assert child["retry_parent_run_id"] == parent_run["run_id"]
    assert child["signal_sources"] == ["hr_critical"]
    assert any(
        event.get("status") == "signal_terminal_one_shot"
        and event.get("outcome") == "not_replayed"
        for event in parent_run["events"]
    )
