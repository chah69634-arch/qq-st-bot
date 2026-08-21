from __future__ import annotations

from core.event_context import EventContext
from core.event_context_observer import record, reset_for_tests, snapshot


def test_disabled_observer_does_not_write_or_count(monkeypatch, sandbox):
    monkeypatch.setattr("core.event_context_observer.config", lambda: {"mode": "disabled"})
    reset_for_tests()
    record(stage="ingress", disposition="accepted")
    assert snapshot()["run_state"] == "not_run"
    assert not sandbox.event_context_trace().exists()


def test_observer_trace_is_content_free(monkeypatch, sandbox):
    monkeypatch.setattr("core.event_context_observer.config", lambda: {"mode": "observe"})
    reset_for_tests()
    context = EventContext.from_ingress(
        uid="private-owner-id", char_id="char-observe", ingress_event_id="private-ingress-id",
        dedupe_key="private-dedupe", source="desktop", channel="desktop", kind="user_message",
    ).with_turn("private-turn-id")
    record(stage="evidence", disposition="committed", context=context)
    text = sandbox.event_context_trace().read_text(encoding="utf-8")
    assert "private-owner-id" not in text
    assert "private-ingress-id" not in text
    assert "private-turn-id" not in text
    assert snapshot()["counts"]["evidence:committed"] == 1


def test_observer_rebuilds_linkage_and_latency_after_process_reset(monkeypatch, sandbox):
    monkeypatch.setattr("core.event_context_observer.config", lambda: {"mode": "observe"})
    reset_for_tests()
    context = EventContext.from_ingress(
        uid="owner-restart", char_id="char-restart", ingress_event_id="ingress-restart",
        dedupe_key="dedupe-restart", source="qq", channel="qq", kind="user_message",
    )
    record(stage="ingress", disposition="accepted", context=context)
    started_at = 100.0
    monkeypatch.setattr("core.event_context_observer.time.monotonic", lambda: 100.012)
    record(
        stage="evidence", disposition="committed",
        context=context.with_turn("turn-restart"), started_at=started_at,
    )

    reset_for_tests()  # Simulate a fresh process; the JSONL remains durable.
    result = snapshot()

    assert result["chains"] == {
        "ingress": 1, "committed": 1, "linked": 1, "orphan": 0,
        "propagation_rate": 1.0,
    }
    assert result["latency"]["evidence"]["p95_ms"] == 12
    assert result["trace"]["rows"] == 2


def test_observer_marks_committed_chain_without_ingress_as_orphan(monkeypatch, sandbox):
    monkeypatch.setattr("core.event_context_observer.config", lambda: {"mode": "observe"})
    context = EventContext.from_ingress(
        uid="owner-orphan", char_id="char-orphan", ingress_event_id="ingress-orphan",
        dedupe_key="dedupe-orphan", source="legacy", channel="system", kind="trigger",
    ).with_turn("turn-orphan")
    record(stage="evidence", disposition="committed", context=context, orphan=True)

    assert snapshot()["chains"]["orphan"] == 1
