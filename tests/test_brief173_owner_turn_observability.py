"""Focused tests for the redacted owner-turn observability projection."""

import json
from unittest.mock import patch

from fastapi.testclient import TestClient


SECRET = "brief173-observability-admin-secret"


def _client(monkeypatch):
    monkeypatch.setattr("admin.auth.get_admin_secret", lambda: SECRET)
    from admin.admin_server import app

    return TestClient(app, raise_server_exceptions=False)


def _write(sandbox, label, client_id, status, created_at):
    from core import owner_turn_receipts

    message = f"message-{client_id}"
    owner_turn_receipts.write(
        caller_label=label,
        client_turn_id=client_id,
        request_digest=owner_turn_receipts.request_hash(
            message=message, reply_to=None, upload_ids=[]
        ),
        status=status,
        canonical_turn_id=f"canonical-{client_id}" if status == "completed" else None,
        created_at=created_at,
    )


def test_owner_turn_observability_is_scoped_paginated_and_redacted(sandbox, monkeypatch):
    _write(sandbox, "hardware-a", "turn-a", "completed", 100.0)
    _write(sandbox, "hardware-b", "turn-b", "failed", 200.0)
    _write(sandbox, "hardware-c", "turn-c", "running", 300.0)
    client = _client(monkeypatch)

    assert client.get("/observability/owner-turns").status_code == 401
    first = client.get(
        "/observability/owner-turns?limit=1",
        headers={"Authorization": f"Bearer {SECRET}"},
    )
    assert first.status_code == 200
    payload = first.json()
    assert payload["count"] == 1
    assert payload["entries"][0]["client_turn_id"] == "turn-c"
    assert payload["entries"][0]["status"] == "interrupted_unknown"
    assert payload["entries"][0]["error_code"] == "execution_outcome_unknown"
    assert set(payload["entries"][0]) == {
        "caller",
        "client_turn_id",
        "canonical_turn_id",
        "status",
        "created_at",
        "updated_at",
        "error_code",
    }
    assert "request_hash" not in json.dumps(payload)
    assert payload["status_counts"]["interrupted_unknown"] == 1

    cursor = payload["next_cursor"]
    assert cursor
    second = client.get(
        f"/observability/owner-turns?limit=1&cursor={cursor}",
        headers={"Authorization": f"Bearer {SECRET}"},
    ).json()
    assert second["entries"][0]["client_turn_id"] == "turn-b"

    filtered = client.get(
        "/observability/owner-turns?caller=hardware-a&status=completed&created_after=99&created_before=101",
        headers={"Authorization": f"Bearer {SECRET}"},
    ).json()
    assert [row["client_turn_id"] for row in filtered["entries"]] == ["turn-a"]


def test_owner_turn_observability_rejects_path_like_filters(sandbox, monkeypatch):
    client = _client(monkeypatch)
    response = client.get(
        "/observability/owner-turns?caller=..%2Fsecrets",
        headers={"Authorization": f"Bearer {SECRET}"},
    )
    assert response.status_code == 422


def test_owner_turn_cursor_accepts_dot_bytes_inside_signature():
    from core import owner_turn_receipts

    sort_key = (-300.0, "hardware-c", "turn-c", "receipt.json")
    digest = b"." * 32
    with patch("core.owner_turn_receipts.hmac.new") as hmac_new:
        hmac_new.return_value.digest.return_value = digest
        cursor = owner_turn_receipts._cursor_encode(sort_key)
        assert owner_turn_receipts._cursor_decode(cursor) == sort_key
