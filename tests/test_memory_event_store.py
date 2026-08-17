from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor

from tests.fixtures.public_assets import TEST_CHAR_ID, TEST_PEER_CHAR_ID


def _scope(uid: str, char_id: str):
    from core.memory.scope import MemoryScope

    return MemoryScope.reality_scope(uid, char_id)


def _event(event_id: str, *, uid: str = "", char_id: str = "", **extra):
    value = {
        "event_id": event_id,
        "turn_id": "turn-fixture-001",
        "seq": 1,
        "occurred_at": 1700000000.0,
        "ingested_at": 1700000001.0,
        "uid": uid,
        "char_id": char_id,
        "realm": "reality",
        "kind": "owner_chat",
        "actor": "owner",
        "channel": "desktop",
        "source": "fixture",
        "raw_payload_json": {"message": "raw fixture"},
        "raw_text": "raw fixture",
        "visible_text": "visible fixture",
        "memory_text": "clean fixture",
        "media_refs_json": [{"kind": "image", "ref": "media-fixture-001"}],
        "redaction_state": "scrubbed",
    }
    value.update(extra)
    return value


def test_event_store_initializes_schema_and_resolves_per_character_path(sandbox):
    from core.memory import event_store
    from core.memory.path_resolver import resolve_path

    scope_a = _scope("event-store-owner", TEST_CHAR_ID)
    scope_b = _scope("event-store-owner", TEST_PEER_CHAR_ID)
    path_a = resolve_path(scope_a, "event_store")
    path_b = resolve_path(scope_b, "event_store")
    assert path_a != path_b
    assert not path_a.exists()
    assert event_store.schema_status(scope_a).to_dict()["exists"] is False

    status = event_store.initialize(scope_a)
    assert status.healthy is True
    assert status.schema_version == event_store.SCHEMA_VERSION
    assert {"events", "event_edges", "event_topics"} <= set(status.tables)
    assert path_a.exists()
    assert not path_b.exists()


def test_event_store_append_is_idempotent_and_preserves_raw_and_clean_fields(sandbox):
    from core.memory import event_store

    scope = _scope("event-store-append-owner", TEST_CHAR_ID)
    first = event_store.append_event(scope, _event("event-fixture-001"))
    duplicate = event_store.append_event(scope, _event("event-fixture-001", raw_text="different raw"))
    assert first.to_dict() == {"ok": True, "inserted": True, "event_id": "event-fixture-001", "error_code": ""}
    assert duplicate.inserted is False and duplicate.error_code == "duplicate"

    path = event_store.resolve_path(scope, "event_store")
    with sqlite3.connect(path) as connection:
        row = connection.execute(
            "SELECT uid, char_id, raw_payload_json, raw_text, visible_text, memory_text, media_refs_json FROM events"
        ).fetchone()
    assert row[0:2] == (scope.uid, scope.character_id)
    assert '"message":"raw fixture"' in row[2]
    assert row[3:] == ("raw fixture", "visible fixture", "clean fixture", '[{"kind":"image","ref":"media-fixture-001"}]')


def test_event_store_concurrent_same_scope_writes_are_isolated_and_complete(sandbox):
    from core.memory import event_store

    scope = _scope("event-store-concurrent-owner", TEST_CHAR_ID)

    def write(index: int):
        return event_store.append_event(scope, _event(f"event-concurrent-{index}"))

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(write, range(24)))
    assert all(result.ok and result.inserted for result in results)

    path = event_store.resolve_path(scope, "event_store")
    with sqlite3.connect(path) as connection:
        count = connection.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    assert count == 24


def test_event_store_upgrade_and_corrupt_database_fail_closed(sandbox):
    from core.memory import event_store

    upgrade_scope = _scope("event-store-upgrade-owner", TEST_CHAR_ID)
    upgrade_path = event_store.resolve_path(upgrade_scope, "event_store")
    upgrade_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(upgrade_path) as connection:
        connection.execute("PRAGMA user_version=0")
    upgraded = event_store.initialize(upgrade_scope)
    assert upgraded.healthy is True
    assert upgraded.schema_version == event_store.SCHEMA_VERSION

    corrupt_scope = _scope("event-store-corrupt-owner", TEST_CHAR_ID)
    corrupt_path = event_store.resolve_path(corrupt_scope, "event_store")
    corrupt_path.parent.mkdir(parents=True, exist_ok=True)
    corrupt_path.write_bytes(b"not a sqlite database")
    status = event_store.schema_status(corrupt_scope)
    result = event_store.append_event(corrupt_scope, _event("event-corrupt-001"))
    assert status.healthy is False and status.error_code == "database_error"
    assert result.ok is False and result.error_code == "database_error"


def test_event_store_rejects_cross_scope_and_invalid_scope_without_writes(sandbox):
    from core.memory import event_store
    from core.memory.scope import MemoryScope

    scope = _scope("event-store-scope-owner", TEST_CHAR_ID)
    mismatch = event_store.append_event(scope, _event("event-mismatch", uid="other-owner", char_id=TEST_CHAR_ID))
    invalid = event_store.append_event(MemoryScope.global_scope("event-store-scope-owner"), _event("event-invalid"))
    malformed = event_store.append_event(scope, object())
    assert mismatch.error_code == "invalid_event"
    assert invalid.error_code == "invalid_scope"
    assert malformed.error_code == "invalid_event"


def test_event_store_status_endpoint_is_read_only(sandbox):
    import asyncio
    from admin.routers.memory import get_event_store_status
    from core.memory import event_store

    scope = _scope("event-store-api-owner", TEST_CHAR_ID)
    event_store.initialize(scope)
    result = asyncio.run(get_event_store_status(scope.uid, char_id=TEST_CHAR_ID, auth=None))
    assert result["user_id"] == scope.uid
    assert result["char_id"] == TEST_CHAR_ID
    assert result["schema_version"] == event_store.SCHEMA_VERSION


def test_event_store_writes_deterministic_edges_and_explicit_cross_turn_links(sandbox):
    from core.memory import event_store

    scope = _scope("event-edge-owner", TEST_CHAR_ID)
    first = _event("edge-first", turn_id="turn-1", seq=0, occurred_at=1.0, stream="desktop-main")
    second = _event("edge-second", turn_id="turn-2", seq=0, occurred_at=2.0, stream="desktop-main")
    user = _event("edge-user", turn_id="turn-3", seq=0, occurred_at=3.0, actor="user")
    assistant = _event(
        "edge-assistant", turn_id="turn-3", seq=1, occurred_at=3.0,
        actor="assistant", triggered_by_event_id="edge-first",
        derived_from_event_id="edge-second", correction_of_event_id="edge-first",
        media_of_event_id="edge-user",
    )
    for item in (first, second, user, assistant):
        assert event_store.append_event(scope, item).ok

    path = event_store.resolve_path(scope, "event_store")
    with sqlite3.connect(path) as connection:
        rows = connection.execute(
            "SELECT from_event_id, to_event_id, relation_type, origin, confidence, schema_version "
            "FROM event_edges ORDER BY edge_id"
        ).fetchall()
    relations = {(row[0], row[1], row[2]) for row in rows}
    assert ("edge-first", "edge-second", "next") in relations
    assert ("edge-second", "edge-first", "previous") in relations
    assert ("edge-user", "edge-assistant", "same_turn") in relations
    assert ("edge-assistant", "edge-user", "reply_to") in relations
    assert ("edge-assistant", "edge-first", "triggered_by") in relations
    assert ("edge-assistant", "edge-second", "derived_from") in relations
    assert ("edge-assistant", "edge-first", "correction_of") in relations
    assert ("edge-assistant", "edge-user", "media_of") in relations
    assert all(row[3:] == ("system", 1.0, event_store.SCHEMA_VERSION) for row in rows)

    snapshot = event_store.edge_observability_snapshot(scope)
    assert snapshot["edge_count"] == len(rows)
    assert snapshot["dangling_count"] == 0
    assert snapshot["by_relation"]["same_turn"] == 1


def test_event_edges_are_realm_scoped_atomic_and_report_dangling_endpoints(sandbox, monkeypatch):
    from core.memory import event_query, event_store

    scope = _scope("event-edge-boundary", TEST_CHAR_ID)
    assert event_store.append_event(scope, _event("edge-good", occurred_at=1.0)).ok
    assert event_store.append_event(scope, _event("edge-dream", realm="dream")).error_code == "invalid_event"

    original_edge_builder = event_store._ensure_deterministic_edges
    monkeypatch.setattr(event_store, "_ensure_deterministic_edges", lambda *_args: (_ for _ in ()).throw(RuntimeError("edge fail")))
    failed = event_store.append_event(scope, _event("edge-rollback", occurred_at=2.0))
    assert failed.error_code == "database_error"
    assert event_query.get_event(scope, "edge-rollback") is None

    monkeypatch.setattr(event_store, "_ensure_deterministic_edges", original_edge_builder)
    assert event_store.append_event(scope, _event("edge-next", occurred_at=2.0)).ok
    path = event_store.resolve_path(scope, "event_store")
    with sqlite3.connect(path) as connection:
        connection.execute("DELETE FROM events WHERE event_id = ?", ("edge-good",))
    related = event_query.related(scope, "edge-next", cursor="", limit=10)
    assert related is not None
    assert any(item["related_event_id"] == "edge-good" and item["dangling"] for item in related["items"])
    assert event_store.edge_observability_snapshot(scope)["dangling_count"] >= 1
