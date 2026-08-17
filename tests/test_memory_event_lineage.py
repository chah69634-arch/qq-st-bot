from __future__ import annotations

from core.write_envelope import stamp_user_chat
from tests.fixtures.public_assets import TEST_CHAR_ID


def _capture(uid: str, turn_id: str) -> list[str]:
    from core.memory.fixation_pipeline import capture_turn
    from core.memory.lineage import event_ids_for_turn

    capture_turn(
        uid, "lineage user evidence", "lineage assistant evidence",
        turn_id=turn_id, char_id=TEST_CHAR_ID, envelope=stamp_user_chat(),
    )
    return event_ids_for_turn(turn_id)


def test_episode_and_storyline_node_resolve_direct_event_evidence_after_midterm_expiry(sandbox):
    from core.memory import mid_term, storyline
    from core.memory.episodic_memory import write_episode
    from core.memory.lineage import resolve_episode, resolve_storyline_node

    uid = "lineage-resolved"
    source_ids = _capture(uid, "lineage-resolved-turn")
    mid_term.append(
        uid, "compressed evidence", mid_id="mt_lineage", source_turn_id="lineage-resolved-turn",
        source_event_ids=source_ids, char_id=TEST_CHAR_ID,
    )
    write_episode(uid, {
        "id": "ep_lineage", "timestamp": 1_800_000_000, "raw_facts": ["fact"],
        "topic_keywords": ["topic"], "emotion_peak": "neutral", "narrative_summary": "summary",
        "strength": 0.7, "source_mid_ids": ["mt_lineage"], "source_event_ids": source_ids,
    }, char_id=TEST_CHAR_ID)
    arc_id = storyline.open_arc(uid, char_id=TEST_CHAR_ID, title="lineage arc", tags=[])
    node_id = storyline.append_node(
        uid, char_id=TEST_CHAR_ID, arc_id=arc_id, summary="node", ts=1_800_000_001,
        source_ids=source_ids,
    )

    # Simulate mid-term expiry/removal. Episode lineage must remain raw-event based.
    assert mid_term.delete_event(uid, "mt_lineage", char_id=TEST_CHAR_ID)
    episode = resolve_episode(uid, "ep_lineage", char_id=TEST_CHAR_ID)
    node = resolve_storyline_node(uid, arc_id, node_id or "", char_id=TEST_CHAR_ID)

    assert episode and episode["lineage_status"] == "resolved"
    assert [event["event_id"] for event in episode["events"]] == source_ids
    assert node and node["lineage_status"] == "resolved"
    assert [event["event_id"] for event in node["events"]] == source_ids


def test_legacy_lineage_is_unknown_and_dry_run_does_not_write_back(sandbox):
    from core.memory import mid_term, storyline
    from core.memory.episodic_memory import _load_memories, write_episode
    from core.memory.lineage import dry_run, resolve_episode, resolve_storyline_node

    uid = "lineage-legacy"
    turn_id = "lineage-legacy-turn"
    _capture(uid, turn_id)
    mid_term.append(uid, "legacy compressed", mid_id="mt_legacy", source_turn_id=turn_id, char_id=TEST_CHAR_ID)
    write_episode(uid, {
        "id": "ep_legacy", "timestamp": 1_800_000_010, "raw_facts": ["legacy"],
        "topic_keywords": [], "emotion_peak": "neutral", "narrative_summary": "legacy summary",
        "strength": 0.5, "source_mid_ids": ["mt_legacy"],
    }, char_id=TEST_CHAR_ID)
    arc_id = storyline.open_arc(uid, char_id=TEST_CHAR_ID, title="legacy arc", tags=[])
    node_id = storyline.append_node(uid, char_id=TEST_CHAR_ID, arc_id=arc_id, summary="old node", ts=1_800_000_011)

    report = dry_run(uid, char_id=TEST_CHAR_ID)
    episode = resolve_episode(uid, "ep_legacy", char_id=TEST_CHAR_ID)
    node = resolve_storyline_node(uid, arc_id, node_id or "", char_id=TEST_CHAR_ID)

    assert report["dry_run"] is True
    assert report["mid_term_backfill_candidates"] == 1
    assert report["episodic_backfill_candidates"] == 1
    assert report["storyline_nodes"] == "append_only_no_backfill"
    assert _load_memories(uid, char_id=TEST_CHAR_ID)[0].get("source_event_ids") == []
    assert episode and episode["lineage_status"] == "legacy_unknown"
    assert node and node["lineage_status"] == "legacy_unknown"

    write_episode(uid, {
        "id": "ep_deleted_event", "timestamp": 1_800_000_012, "raw_facts": ["deleted"],
        "topic_keywords": [], "emotion_peak": "neutral", "narrative_summary": "deleted evidence",
        "strength": 0.5, "source_event_ids": ["deleted-event-id"],
    }, char_id=TEST_CHAR_ID)
    deleted = resolve_episode(uid, "ep_deleted_event", char_id=TEST_CHAR_ID)
    assert deleted and deleted["lineage_status"] == "legacy_unknown"
    assert deleted["events"] == [{"event_id": "deleted-event-id", "status": "missing"}]


def test_storyline_aggregator_passes_episode_event_range_to_new_node(sandbox):
    from core.memory import storyline
    from core.scheduler.triggers.storyline_weekly import _apply_ops

    uid = "lineage-weekly"
    source_ids = ["turn-a:user", "turn-a:assistant"]
    _apply_ops(uid, TEST_CHAR_ID, [
        {"op": "open_arc", "title": "weekly lineage", "tags": []},
        {"op": "append_node", "arc_title": "weekly lineage", "summary": "node", "ts": 1_800_000_100},
    ], source_event_ids=source_ids)

    node = storyline.load(uid, char_id=TEST_CHAR_ID)["arcs"][0]["nodes"][0]
    assert node["source_ids"] == source_ids


def test_eviction_inbox_deduplicates_retry_and_unions_event_evidence(sandbox):
    from core.memory import storyline

    uid = "lineage-inbox"
    storyline.append_to_inbox(uid, [{
        "id": "ep_retry", "summary": "snapshot", "ts": 1.0, "strength": 0.5,
        "source_event_ids": ["turn-1:user"],
    }], char_id=TEST_CHAR_ID)
    storyline.append_to_inbox(uid, [{
        "id": "ep_retry", "summary": "snapshot", "ts": 1.0, "strength": 0.5,
        "source_event_ids": ["turn-1:assistant"],
    }], char_id=TEST_CHAR_ID)

    entries = storyline.load_inbox(uid, char_id=TEST_CHAR_ID)
    assert len(entries) == 1
    assert entries[0]["source_event_ids"] == ["turn-1:user", "turn-1:assistant"]
