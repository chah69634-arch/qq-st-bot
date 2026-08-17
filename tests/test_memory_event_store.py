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
