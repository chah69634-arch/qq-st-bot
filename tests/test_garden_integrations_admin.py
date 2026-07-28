"""Admin control-surface contracts for the optional Galatea Garden bridge."""

from __future__ import annotations

import asyncio
import inspect
from pathlib import Path

from admin.token_registry import TokenRecord


def _record(*, disabled: bool = False) -> TokenRecord:
    return TokenRecord(
        label="garden-wake",
        hash="sha256:not-a-secret",
        scopes=frozenset({"integration.write"}),
        expires_at=None,
        disabled=disabled,
    )


def test_unconfigured_garden_status_is_safe_and_side_effect_free(monkeypatch):
    from admin.routers import integrations

    monkeypatch.setattr(integrations, "_active_scope", lambda: ("", ""))
    monkeypatch.setattr(integrations.token_registry, "list_records", lambda: [])
    status = integrations.garden_status()["garden"]

    assert status["enabled"] is False
    assert status["integration_token"] == "missing"
    assert status["bridge_status"] == "unknown"
    assert status["pending_count"] == 0


def test_status_redacts_machine_secret_and_event_identity(monkeypatch):
    from admin.routers import integrations

    secret = "machine-token-must-not-leak"
    monkeypatch.setenv("GARDEN_MACHINE_TOKEN", secret)
    monkeypatch.setattr(integrations, "_active_scope", lambda: ("owner-a", "char-a"))
    monkeypatch.setattr(integrations.token_registry, "list_records", lambda: [_record()])
    monkeypatch.setattr(integrations, "_garden_entry", lambda *_: {
        "last_received_at": 100.0,
        "next_attempt_at": 0.0,
        "pending_count": 2,
        "processing_count": 1,
        "expired_count": 3,
        "consecutive_failures": 4,
        "last_success_at": 99.0,
        "external_id": "forbidden-id",
        "message": "forbidden message",
        "raw_hash": "forbidden-hash",
        "last_cursor": "forbidden-cursor",
    })
    monkeypatch.setattr(integrations, "_scheduler_running", lambda: True)

    serialized = repr(integrations.garden_status())
    assert "configured" in serialized
    for forbidden in (secret, "forbidden-id", "forbidden message", "forbidden-hash", "forbidden-cursor"):
        assert forbidden not in serialized


def test_manual_test_wake_uses_formal_garden_ingress_without_inline_drain(monkeypatch):
    from admin.routers import integrations
    from admin.routers import wake_bridge

    received = {}

    async def fake_submit(body):
        received.update(body)
        return {"status": "pending"}

    monkeypatch.setattr(integrations, "_integration_token_configured", lambda: True)
    monkeypatch.setattr(integrations, "_active_scope", lambda: ("owner-a", "char-a"))
    monkeypatch.setattr(wake_bridge, "submit_garden_wake", fake_submit)

    assert asyncio.run(integrations.send_garden_test_wake(_auth=object())) == {"status": "pending"}
    assert received["provider"] == "galatea_garden"
    assert received["reason"] == "manual_test"
    assert received["uid"] == "owner-a" and received["char_id"] == "char-a"
    source = inspect.getsource(integrations.send_garden_test_wake)
    assert "WakeBridge" not in source
    assert "drain_due" not in source
    assert "turn_sink" not in source


def test_missing_integration_token_rejects_test_without_ingress(monkeypatch):
    from admin.routers import integrations

    monkeypatch.setattr(integrations, "_integration_token_configured", lambda: False)
    result = asyncio.run(integrations.send_garden_test_wake(_auth=object()))
    assert result == {"status": "rejected", "reason": "integration_token_missing"}


def test_status_route_requires_auth_and_returns_only_redacted_fields(sandbox, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from admin import token_registry
    from admin.routers import integrations

    app = FastAPI()
    app.include_router(integrations.router)
    client = TestClient(app)
    assert client.get("/integrations/garden/status").status_code == 401

    token = token_registry.create_token("garden-panel", scopes=["admin"])
    monkeypatch.setattr(integrations, "_active_scope", lambda: ("owner-a", "char-a"))
    monkeypatch.setattr(integrations, "_garden_entry", lambda *_: {"pending_count": 1})
    response = client.get("/integrations/garden/status", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    garden = response.json()["garden"]
    assert garden["pending_count"] == 1
    assert "token" not in garden and "cursor" not in garden and "message" not in garden


def test_admin_page_template_and_actions_never_embed_secrets():
    root = Path(__file__).parent.parent
    page = (root / "admin/static/pages/integrations.html").read_text(encoding="utf-8")
    script = (root / "admin/static/js/integrations.js").read_text(encoding="utf-8")
    index = (root / "admin/static/index.html").read_text(encoding="utf-8")

    assert 'data-page="integrations"' in index
    assert 'id="page-integrations" data-page-fragment="integrations"' in index
    assert "/integrations/garden/test-wake" in script
    assert "manual_test" in page
    assert "GARDEN_MACHINE_TOKEN" in script
    assert "<请在本地填写>" in script
    assert "PRESENCE_INTEGRATION_TOKEN" in script
    assert "GARDEN_MACHINE_TOKEN = \"emt_" not in page + script
