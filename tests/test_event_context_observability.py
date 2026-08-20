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
