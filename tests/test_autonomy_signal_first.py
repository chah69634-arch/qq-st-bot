from __future__ import annotations

import time


def test_signal_contract_merges_one_opportunity_with_conservative_expiry():
    from core.autonomy.models import ActionMode, Opportunity, Signal

    signals = [
        Signal(
            source="interval",
            evidence=[{"fact": "elapsed", "seconds": 3600}],
            reason="interval elapsed",
            expiry=500,
            priority=0.2,
            action_mode=ActionMode.REFLECT.value,
        ),
        Signal(
            source="sensor",
            evidence=[{"fact": "attention_window", "value": "bounded"}],
            reason="sensor evidence is fresh",
            expiry=400,
            priority=0.8,
            memory_query="attention",
            action_mode=ActionMode.TALK.value,
        ),
    ]
    opportunity = Opportunity.merge(signals, now=100)
    payload = opportunity.to_dict()
    assert payload["version"] == "autonomy-opportunity.v1"
    assert payload["priority"] == 0.8
    assert payload["expiry"] == 400
    assert payload["action_mode"] == "talk"
    assert payload["memory_query"] == ["attention"]
    assert [item["source"] for item in payload["signals"]] == ["interval", "sensor"]


def test_enqueue_opportunity_persists_one_job_and_all_signal_sources(sandbox):
    from core.autonomy import store
    from core.autonomy.models import Signal

    job, status = store.enqueue_opportunity(
        "owner",
        "char",
        [
            Signal(source="interval", reason="one", expiry=time.time() + 600),
            Signal(source="overflow", reason="two", expiry=time.time() + 600),
        ],
        dedupe_key="same-tick",
    )
    assert status == "queued"
    assert job is not None
    assert job.source == "autonomy"
    assert job.signal_sources == ["interval", "overflow"]
    loaded = store.load("owner", "char")
    assert loaded["jobs"][0]["opportunity"]["version"] == "autonomy-opportunity.v1"
    assert len(loaded["jobs"][0]["opportunity"]["signals"]) == 2


def test_opportunity_prompt_contains_facts_and_explicit_reality_time():
    from core.autonomy.models import Job, Signal, Opportunity
    from core.autonomy.runner import _opportunity_context

    opportunity = Opportunity.merge([
        Signal(
            source="schedule",
            evidence=[{"fact": "configured_schedule_due", "configured_time": "12:00"}],
            reason="configured evaluation time is due",
            expiry=time.time() + 600,
        )
    ])
    prompt = _opportunity_context(Job(uid="owner", char_id="char", source="autonomy", opportunity=opportunity.to_dict()))
    assert "autonomy-opportunity.v1" in prompt
    assert "configured_schedule_due" in prompt
    assert "reality_time" in prompt
    assert "do not infer user state" in prompt
