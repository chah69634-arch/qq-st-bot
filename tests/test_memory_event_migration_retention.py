from __future__ import annotations

import importlib.util
from pathlib import Path

from fastapi.testclient import TestClient

from tests.fixtures.public_assets import TEST_CHAR_ID

SECRET = "memory-event-migration-admin-secret"


def _scope(uid: str):
    from core.memory.scope import MemoryScope

    return MemoryScope.reality_scope(uid, TEST_CHAR_ID)


def _client(monkeypatch) -> TestClient:
    monkeypatch.setattr("admin.auth.get_admin_secret", lambda: SECRET)
    from admin.admin_server import app

    return TestClient(app, raise_server_exceptions=False)


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {SECRET}"}


def _legacy_log(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "2026-08-01.md").write_text(
        """## 12:34
**用户**：第一行
第二行
> speaker:user turn_id:old-a
---
## 12:34
**用户**：第一行
第二行
> speaker:user turn_id:old-a
---
## 12:35
**任意显示名**：不可信角色
> speaker:user
---
""",
        encoding="utf-8",
    )
    return root


def test_dry_run_is_read_only_and_duplicate_blocks_are_deterministic(sandbox, tmp_path):
    from core.memory.event_migration import scan_legacy
    from core.memory.path_resolver import resolve_path

    scope = _scope("migration-dry-run")
    plan = scan_legacy(scope, source_dir=_legacy_log(tmp_path / "legacy"))
    assert plan["total"] == 3
    assert plan["parsed"] == 2
    assert plan["malformed"] == plan["legacy_unknown"] == 1
    assert plan["entries"][0].event_id == plan["entries"][1].event_id
    assert not resolve_path(scope, "event_store").exists()
    assert not resolve_path(scope, "event_migration_state").exists()


def test_migration_is_batched_idempotent_and_recovers_after_failure(sandbox, tmp_path, monkeypatch):
    from core.memory import event_migration, event_query, event_store

    scope = _scope("migration-recovery")
    plan = event_migration.scan_legacy(scope, source_dir=_legacy_log(tmp_path / "legacy"))
    failed = event_store.AppendResult(False, False, plan["entries"][0].event_id, "database_error")
    original = event_migration.event_store.append_event
    monkeypatch.setattr(event_migration.event_store, "append_event", lambda *_args: failed)
    paused = event_migration.apply_batch(scope, plan, batch_size=1, backup={"verified": True})
    assert paused["status"] == "paused"
    assert paused["next_offset"] == 0
    assert paused["failed"] == 1

    monkeypatch.setattr(event_migration.event_store, "append_event", original)
    first = event_migration.apply_batch(scope, plan, batch_size=1, backup={"verified": True})
    assert first["next_offset"] == 1
    completed = event_migration.apply_batch(scope, plan, batch_size=10, backup={"verified": True})
    assert completed["status"] == "completed"
    assert completed["written"] == 2
    assert completed["duplicate"] == 1
    unknown = next(entry for entry in plan["entries"] if entry.kind == "legacy_unknown")
    event = event_query.get_event(scope, unknown.event_id)
    assert event is not None
    assert event["raw_text"] == ""
    assert event["visible_text"].startswith("[legacy_unknown:")


def test_migration_conflict_is_counted_without_overwrite(sandbox, tmp_path):
    from core.memory import event_migration, event_store

    scope = _scope("migration-conflict")
    plan = event_migration.scan_legacy(scope, source_dir=_legacy_log(tmp_path / "legacy"))
    entry = plan["entries"][0]
    assert event_store.append_event(scope, {**entry.event(), "raw_payload_json": {"legacy_ref": "other"}}).inserted
    status = event_migration.apply_batch(scope, plan, batch_size=10, backup={"verified": True})
    # Both identical legacy blocks target the manually occupied deterministic
    # ID, so neither may overwrite it or be mislabeled as a safe duplicate.
    assert status["conflict"] == 2
    assert status["duplicate"] == 0


def test_migration_backup_helper_requires_verification(monkeypatch, tmp_path):
    module_path = Path(__file__).resolve().parents[1] / "scripts" / "migrate_memory_events.py"
    spec = importlib.util.spec_from_file_location("migration_script_fixture", module_path)
    assert spec and spec.loader
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    monkeypatch.setattr(script, "create_snapshot", lambda *_args, **_kwargs: {
        "backup_id": "backup-fixture", "file_count": 3, "protection_mode": "protected_volume",
    })
    monkeypatch.setattr(script, "verify_snapshot", lambda _path: {"ok": True, "file_count": 3})
    checksum = "a" * 64
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    (snapshot / "manifest.sha256").write_text(checksum, encoding="ascii")
    assert script._backup(snapshot) == {
        "backup_id": "backup-fixture", "file_count": 3, "verified": True, "manifest_sha256": checksum,
        "protection_mode": "protected_volume",
    }


def test_tombstone_retains_edges_and_hides_payload_in_admin_views(sandbox, monkeypatch):
    from core.memory import event_query, event_store, lineage
    from core.memory.path_resolver import resolve_path
    from core.safe_write import safe_write_json

    scope = _scope("migration-tombstone")
    assert event_store.append_event(scope, {
        "event_id": "retain-edge-a", "occurred_at": 1, "realm": "reality", "kind": "owner_chat",
        "actor": "user", "raw_text": "forget me", "visible_text": "forget me", "memory_text": "forget me",
        "media_refs_json": [{"filename": "private.png"}],
    }).inserted
    assert event_store.append_event(scope, {
        "event_id": "retain-edge-b", "occurred_at": 2, "realm": "reality", "kind": "owner_chat",
        "actor": "assistant", "raw_text": "keep me", "visible_text": "keep me", "memory_text": "keep me",
        "reply_to_event_id": "retain-edge-a",
    }).inserted

    client = _client(monkeypatch)
    response = client.delete("/memory-events/retain-edge-a", params={"uid": scope.uid, "char_id": TEST_CHAR_ID, "realm": "reality"}, headers=_headers())
    assert response.status_code == 200
    assert response.json()["edges"] == "retained"
    again = client.delete("/memory-events/retain-edge-a", params={"uid": scope.uid, "char_id": TEST_CHAR_ID, "realm": "reality"}, headers=_headers())
    assert again.status_code == 200 and again.json()["changed"] is False

    tombstoned = event_query.get_event(scope, "retain-edge-a")
    assert tombstoned and tombstoned["tombstoned"] is True
    assert tombstoned["raw_text"] == tombstoned["visible_text"] == tombstoned["memory_text"] == ""
    assert tombstoned["media_refs"] == []
    related = event_query.related(scope, "retain-edge-b", cursor="", limit=10)
    assert related and related["items"][0]["event"]["tombstoned"] is True
    assert safe_write_json(resolve_path(scope, "episodic"), [{
        "id": "derived-retains-lineage", "source_event_ids": ["retain-edge-a"],
    }])
    derived = lineage.resolve_episode(scope.uid, "derived-retains-lineage", char_id=TEST_CHAR_ID)
    assert derived and derived["lineage_status"] == "resolved"
    assert derived["events"][0]["tombstoned"] is True

    migration_status = client.get("/observability/memory-event-migration", params={"uid": scope.uid, "char_id": TEST_CHAR_ID}, headers=_headers())
    assert migration_status.status_code == 200
    assert "raw_text" not in migration_status.text
    old_delete = client.delete(f"/memory/{scope.uid}/event-log/2026-08-01", params={"char_id": TEST_CHAR_ID}, headers=_headers())
    assert old_delete.status_code == 409
    assert old_delete.json()["detail"]["code"] == "physical_delete_disabled_pending_owner_policy"
