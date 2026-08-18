from __future__ import annotations

import sqlite3
from unittest.mock import patch

import pytest

from tests.fixtures.public_assets import TEST_CHAR_ID


def _events_for(uid: str):
    from core.memory.path_resolver import resolve_path
    from core.memory.scope import MemoryScope

    path = resolve_path(MemoryScope.reality_scope(uid, TEST_CHAR_ID), "event_store")
    with sqlite3.connect(path) as connection:
        return connection.execute(
            "SELECT event_id, turn_id, seq, actor, channel, source, raw_text, visible_text, memory_text, media_refs_json "
            "FROM events ORDER BY seq"
        ).fetchall()


def test_capture_turn_dual_writes_distinct_message_events_with_frozen_scope(sandbox):
    from core.memory.fixation_pipeline import capture_turn
    from core.write_envelope import stamp_user_chat

    turn_id = capture_turn(
        "ledger-dual-owner",
        "memory copy including media context",
        "assistant memory-clean text",
        envelope=stamp_user_chat(),
        char_id=TEST_CHAR_ID,
        turn_id="turn-dual-001",
        event_channel="desktop",
        event_source="user_chat",
        visible_reply="assistant visible text",
        raw_user_text="raw owner text",
        media_refs=[{"kind": "image", "filename": "fixture.png", "sha256": "a" * 64}],
    )

    assert turn_id == "turn-dual-001"
    events = _events_for("ledger-dual-owner")
    assert [row[0] for row in events] == ["turn-dual-001:user", "turn-dual-001:assistant"]
    assert [row[1:6] for row in events] == [
        (turn_id, 0, "user", "desktop", "user_chat"),
        (turn_id, 1, "assistant", "desktop", "user_chat"),
    ]
    assert events[0][6:9] == ("raw owner text", "raw owner text", "memory copy including media context")
    assert events[1][6:9] == ("assistant visible text", "assistant visible text", "assistant memory-clean text")
    assert '"sha256":"' in events[0][9]


def test_capture_turn_writes_rule_topics_and_complete_same_turn_relations(sandbox, monkeypatch):
    from core.memory import event_query
    from core.memory.fixation_pipeline import capture_turn
    from core.memory.scope import MemoryScope
    from core.write_envelope import stamp_user_chat

    monkeypatch.setattr("core.tag_rules.get_tags", lambda _text: {"topic.fixture", "topic.work"})
    uid = "ledger-topic-owner"
    turn_id = capture_turn(
        uid, "controlled topic input", "controlled reply", envelope=stamp_user_chat(),
        char_id=TEST_CHAR_ID, turn_id="turn-topic-001",
    )
    scope = MemoryScope.reality_scope(uid, TEST_CHAR_ID)
    assert event_query.get_event(scope, f"{turn_id}:user")["topics"] == ["topic.fixture", "topic.work"]
    assert event_query.get_event(scope, f"{turn_id}:assistant")["topics"] == ["topic.fixture", "topic.work"]
    related = event_query.related(scope, f"{turn_id}:assistant", cursor="", limit=10)
    assert related and len(related["items"]) == 1
    assert {"same_turn", "reply_to"} <= {
        relation["relation_type"] for relation in related["items"][0]["relations"]
    }


@pytest.mark.parametrize("channel", ["qq", "desktop", "mobile", "scheduler"])
def test_capture_turn_keeps_turn_id_alignment_for_reality_channels(sandbox, channel):
    from core.memory.fixation_pipeline import capture_turn
    from core.write_envelope import stamp_trigger, stamp_user_chat

    uid = f"ledger-channel-{channel}"
    is_trigger = channel == "scheduler"
    turn_id = capture_turn(
        uid,
        "",
        "assistant-only" if is_trigger else "reply",
        envelope=stamp_trigger() if is_trigger else stamp_user_chat(),
        char_id=TEST_CHAR_ID,
        turn_id=f"turn-{channel}",
        trigger_name="morning_greeting" if is_trigger else "",
        event_channel=channel,
        event_source="trigger" if is_trigger else "user_chat",
    )

    events = _events_for(uid)
    assert all(row[1] == turn_id for row in events)
    assert [row[3] for row in events] == (["assistant"] if is_trigger else ["user", "assistant"])
    assert {row[4] for row in events} == {channel}


def test_ledger_failure_does_not_interrupt_legacy_capture_and_emits_signal(sandbox):
    from core.memory.event_store import AppendResult
    from core.memory.fixation_pipeline import capture_turn
    from core.memory.short_term import load
    from core.runtime_signal_observability import _reset_for_tests, snapshot
    from core.write_envelope import stamp_user_chat

    _reset_for_tests()
    with patch("core.memory.event_store.append_event", return_value=AppendResult(False, False, "event", "database_error")):
        turn_id = capture_turn(
            "ledger-failure-owner",
            "user survives",
            "assistant survives",
            envelope=stamp_user_chat(),
            char_id=TEST_CHAR_ID,
            turn_id="turn-failure-001",
        )

    assert turn_id == "turn-failure-001"
    assert [item["content"] for item in load("ledger-failure-owner", char_id=TEST_CHAR_ID)[-2:]] == [
        "user survives",
        "assistant survives",
    ]
    assert any(
        signal["category"] == "memory_event_ledger" and signal["code"] == "append_failed"
        for signal in snapshot()["signals"]
    )


def test_event_store_observability_counts_success_duplicate_and_failure(sandbox):
    import asyncio
    from admin.routers.observability import memory_event_ledger
    from core.memory import event_store
    from core.memory.scope import MemoryScope

    event_store._reset_observability_for_tests()
    scope = MemoryScope.reality_scope("ledger-observe-owner", TEST_CHAR_ID)
    event = {"event_id": "event-observe-001", "actor": "user", "kind": "user_message"}
    assert event_store.append_event(scope, event).inserted
    assert event_store.append_event(scope, event).error_code == "duplicate"
    assert event_store.append_event(scope, {"event_id": ""}).error_code == "invalid_event"

    snapshot = event_store.observability_snapshot()
    assert snapshot["attempted"] == 3
    assert snapshot["written"] == 1
    assert snapshot["duplicates"] == 1
    assert snapshot["failed"] == 1
    assert snapshot["by_character"][TEST_CHAR_ID]["attempted"] == 3
    assert snapshot["by_realm"]["reality"]["written"] == 1
    assert asyncio.run(memory_event_ledger(_auth=None)) == snapshot
