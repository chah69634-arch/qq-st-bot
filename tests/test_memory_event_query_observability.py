from __future__ import annotations

import json
import sqlite3

from fastapi.testclient import TestClient

from tests.fixtures.public_assets import TEST_CHAR_ID, TEST_PEER_CHAR_ID

SECRET = "memory-event-query-admin-secret"


def _client(monkeypatch) -> TestClient:
    monkeypatch.setattr("admin.auth.get_admin_secret", lambda: SECRET)
    from admin.admin_server import app

    return TestClient(app, raise_server_exceptions=False)


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {SECRET}"}


def _seed(uid: str, char_id: str = TEST_CHAR_ID) -> None:
    from core.memory import event_store
    from core.memory.scope import MemoryScope

    scope = MemoryScope.reality_scope(uid, char_id)
    for seq, event_id in enumerate(("event-query-01", "event-query-02", "event-query-03")):
        result = event_store.append_event(scope, {
            "event_id": event_id,
            "turn_id": "turn-query-fixture",
            "seq": seq,
            "occurred_at": 1_700_000_000 + seq,
            "ingested_at": 1_700_000_100 + seq,
            "realm": "reality",
            "kind": "owner_chat",
            "actor": "user" if seq != 1 else "assistant",
            "channel": "desktop",
            "source": "fixture",
            "raw_payload_json": {"credential": "must-not-be-projected"},
            "raw_text": f"raw evidence {seq} sensitive-query-needle",
            "visible_text": f"visible evidence {seq}",
            "memory_text": f"memory evidence {seq}",
            "media_refs_json": [{"kind": "image", "filename": "fixture.png", "sha256": "a" * 64, "path": "C:/private/file.png"}],
        })
        assert result.inserted


def _params(uid: str, char_id: str = TEST_CHAR_ID) -> dict[str, str]:
    return {"uid": uid, "char_id": char_id, "realm": "reality"}


def test_memory_event_query_requires_memory_read_scope(sandbox, monkeypatch):
    client = _client(monkeypatch)
    assert client.get("/memory-events/search", params=_params("event-query-auth")).status_code == 401

    from admin import token_registry
    import yaml

    raw = "emt_memory_event_chat_only"
    token_path = sandbox.auth_tokens_file()
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(yaml.safe_dump({"tokens": [{
        "label": "event-query-chat", "hash": token_registry.hash_token(raw), "scopes": ["chat"],
    }]}), encoding="utf-8")
    token_registry._records = None
    token_registry._mtime = None
    denied = client.get("/memory-events/search", params=_params("event-query-auth"), headers={"Authorization": f"Bearer {raw}"})
    assert denied.status_code == 403
    assert "memory.read" in denied.json()["detail"]


def test_memory_event_query_contract_is_present_in_openapi(sandbox, monkeypatch):
    schema = _client(monkeypatch).get("/openapi.json").json()
    for path in (
        "/memory-events/search",
        "/memory-events/{event_id}",
        "/memory-events/{event_id}/window",
        "/memory-events/{event_id}/related",
        "/memory-events/query-trace",
        "/memory-events/lineage/episodes/{episode_id}",
        "/memory-events/lineage/storyline/{arc_id}/nodes/{node_id}",
        "/memory-events/lineage/dry-run",
    ):
        assert path in schema["paths"]


def test_memory_event_query_reads_only_requested_scope_and_projects_safe_evidence(sandbox, monkeypatch):
    client = _client(monkeypatch)
    uid = "event-query-owner"
    _seed(uid)
    _seed(uid, TEST_PEER_CHAR_ID)

    response = client.get("/memory-events/event-query-02", params=_params(uid), headers=_headers())
    assert response.status_code == 200
    event = response.json()["event"]
    assert event["event_id"] == "event-query-02"
    assert event["char_id"] == TEST_CHAR_ID
    assert event["raw_text"] == "raw evidence 1 sensitive-query-needle"
    assert "raw_payload_json" not in event
    assert event["media_refs"] == [{"kind": "image", "filename": "fixture.png", "sha256": "a" * 64}]
    assert "C:/private/file.png" not in response.text

    cross_char = client.get("/memory-events/event-query-02", params=_params(uid, TEST_PEER_CHAR_ID), headers=_headers())
    assert cross_char.status_code == 200
    assert cross_char.json()["event"]["char_id"] == TEST_PEER_CHAR_ID

    cross_uid = client.get("/memory-events/event-query-02", params=_params("another-owner"), headers=_headers())
    assert cross_uid.status_code == 404
    assert cross_uid.json()["detail"] == {"code": "event_not_found"}
    assert client.get("/memory-events/event-query-02", params={**_params(uid), "realm": "dream"}, headers=_headers()).status_code == 422


def test_memory_event_window_search_related_pagination_and_trace_are_bounded(sandbox, monkeypatch):
    from core.memory.path_resolver import resolve_path
    from core.memory.scope import MemoryScope

    client = _client(monkeypatch)
    uid = "event-query-window"
    _seed(uid)
    scope = MemoryScope.reality_scope(uid, TEST_CHAR_ID)
    with sqlite3.connect(resolve_path(scope, "event_store")) as connection:
        connection.execute(
            "INSERT INTO event_edges (uid, char_id, from_event_id, to_event_id, edge_type, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (uid, TEST_CHAR_ID, "event-query-02", "event-query-01", "same_turn", 1_700_000_200),
        )
        connection.execute(
            "INSERT INTO event_edges (uid, char_id, from_event_id, to_event_id, edge_type, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (uid, TEST_CHAR_ID, "event-query-02", "event-query-03", "same_turn", 1_700_000_201),
        )

    window = client.get("/memory-events/event-query-02/window", params={**_params(uid), "before": 1, "after": 1}, headers=_headers())
    assert window.status_code == 200
    assert [item["event_id"] for item in window.json()["before"]] == ["event-query-01"]
    assert [item["event_id"] for item in window.json()["after"]] == ["event-query-03"]
    assert window.json()["truncation_reason"] == ""
    assert client.get("/memory-events/event-query-02/window", params={**_params(uid), "before": 51}, headers=_headers()).status_code == 422

    first_related = client.get("/memory-events/event-query-02/related", params={**_params(uid), "limit": 1}, headers=_headers())
    assert first_related.status_code == 200
    payload = first_related.json()
    assert payload["items"][0]["related_event_id"] == "event-query-01"
    assert payload["next_cursor"]
    second_related = client.get("/memory-events/event-query-02/related", params={**_params(uid), "limit": 1, "cursor": payload["next_cursor"]}, headers=_headers())
    assert [item["related_event_id"] for item in second_related.json()["items"]] == ["event-query-03"]
    assert client.get("/memory-events/event-query-02/related", params={**_params(uid), "cursor": "not-a-cursor"}, headers=_headers()).status_code == 422

    search = client.get("/memory-events/search", params={**_params(uid), "q": "sensitive-query-needle", "limit": 2}, headers=_headers())
    assert search.status_code == 200
    assert len(search.json()["items"]) == 2
    assert search.json()["next_cursor"]
    assert search.json()["truncation_reason"] == "limit"

    trace = client.get("/memory-events/query-trace", params=_params(uid), headers=_headers())
    assert trace.status_code == 200
    serialized_trace = json.dumps(trace.json(), ensure_ascii=True)
    assert "sensitive-query-needle" not in serialized_trace
    assert "raw evidence" not in serialized_trace
    assert {entry["query_type"] for entry in trace.json()["entries"]} >= {"window", "related", "search"}
    assert all(entry["scope"]["uid"] == uid for entry in trace.json()["entries"])


def test_memory_event_query_handles_missing_and_corrupt_ledgers_without_evidence_leaks(sandbox, monkeypatch):
    from core.memory.path_resolver import resolve_path
    from core.memory.scope import MemoryScope

    client = _client(monkeypatch)
    missing = client.get("/memory-events/missing", params=_params("event-query-missing"), headers=_headers())
    assert missing.status_code == 404
    assert missing.json()["detail"] == {"code": "event_not_found"}

    uid = "event-query-corrupt"
    path = resolve_path(MemoryScope.reality_scope(uid, TEST_CHAR_ID), "event_store")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"not a sqlite ledger: sensitive-query-needle")
    corrupt = client.get("/memory-events/anything", params=_params(uid), headers=_headers())
    assert corrupt.status_code == 503
    assert corrupt.json()["detail"] == {"code": "database_error"}
    assert "sensitive-query-needle" not in corrupt.text
