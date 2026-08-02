"""
tests/test_model_presets_crud.py — W2: model-presets preset/routing-profile CRUD + 连通性测试

覆盖：
  PUT    /model-presets/presets/{name}
  DELETE /model-presets/presets/{name}
  PUT    /model-presets/routing-profiles/{name}
  POST   /model-presets/presets/{name}/test
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient

VALID_TOKEN = "model-presets-test-secret"

_BASE_MODEL_PRESETS = {
    "active_routing": "default",
    "defaults": {"temperature": 1.0},
    "presets": {
        "deepseek-default": {
            "provider_kind": "deepseek",
            "base_url": "https://api.deepseek.com",
            "api_key": "sk-existing-secret-key",
            "model": "deepseek-chat",
            "tool_call_mode": "function_calling",
            "params": {"temperature": 1.0},
        },
    },
    "routing_profiles": {
        "default": {"chat": "deepseek-default", "probe": "deepseek-default"},
    },
}


def _write_cfg(path, model_presets=None, legacy=False):
    if legacy:
        content = {"llm": {"base_url": "https://api.deepseek.com", "api_key": "sk-x", "model": "deepseek-chat"}}
    else:
        content = {"model_presets": model_presets if model_presets is not None else _BASE_MODEL_PRESETS}
    path.write_text(yaml.dump(content, allow_unicode=True), encoding="utf-8")


@pytest.fixture
def admin_client(tmp_path, monkeypatch):
    import admin.routers.settings_llm as sl

    temp_cfg = tmp_path / "config.yaml"
    monkeypatch.setattr(sl, "CONFIG_FILE", temp_cfg)
    monkeypatch.setattr("admin.auth.get_admin_secret", lambda: VALID_TOKEN)

    with patch("core.config_loader.reload_config", return_value=None):
        from admin.routers.settings_llm import router as sl_router
        app = FastAPI()
        app.include_router(sl_router)
        yield TestClient(app), temp_cfg


def _auth():
    return {"Authorization": f"Bearer {VALID_TOKEN}"}


# ── PUT /model-presets/presets/{name} ──────────────────────────────────────────

def test_put_creates_new_preset(admin_client):
    client, temp_cfg = admin_client
    _write_cfg(temp_cfg)

    resp = client.put(
        "/model-presets/presets/claude-sonnet",
        json={
            "provider_kind": "anthropic_compat",
            "base_url": "https://oneapi.example/v1",
            "api_key": "sk-claude-secret-key",
            "model": "claude-sonnet-4-6",
        },
        headers=_auth(),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["preset"]["api_key"] != "sk-claude-secret-key"

    saved = yaml.safe_load(temp_cfg.read_text(encoding="utf-8"))
    new_preset = saved["model_presets"]["presets"]["claude-sonnet"]
    assert new_preset["provider_kind"] == "anthropic_compat"
    assert new_preset["api_key"] == "sk-claude-secret-key"
    # existing preset untouched
    assert "deepseek-default" in saved["model_presets"]["presets"]


def test_put_new_preset_without_provider_kind_rejected(admin_client):
    client, temp_cfg = admin_client
    _write_cfg(temp_cfg)

    resp = client.put(
        "/model-presets/presets/incomplete",
        json={"model": "some-model"},
        headers=_auth(),
    )
    assert resp.status_code == 422

    saved = yaml.safe_load(temp_cfg.read_text(encoding="utf-8"))
    assert "incomplete" not in saved["model_presets"]["presets"]


def test_put_unknown_provider_kind_rejected(admin_client):
    client, temp_cfg = admin_client
    _write_cfg(temp_cfg)

    resp = client.put(
        "/model-presets/presets/bad-kind",
        json={"provider_kind": "not_a_real_provider", "model": "x"},
        headers=_auth(),
    )
    assert resp.status_code == 422


def test_put_updates_existing_preset_merges_params(admin_client):
    client, temp_cfg = admin_client
    _write_cfg(temp_cfg)

    resp = client.put(
        "/model-presets/presets/deepseek-default",
        json={"params": {"temperature": 0.5}},
        headers=_auth(),
    )
    assert resp.status_code == 200

    saved = yaml.safe_load(temp_cfg.read_text(encoding="utf-8"))
    preset = saved["model_presets"]["presets"]["deepseek-default"]
    assert preset["params"]["temperature"] == 0.5
    # unrelated fields survive the partial update
    assert preset["model"] == "deepseek-chat"
    assert preset["base_url"] == "https://api.deepseek.com"


def test_put_preset_accepts_explicit_protocols_and_rejects_unknown_value(admin_client):
    client, temp_cfg = admin_client
    _write_cfg(temp_cfg)

    ok = client.put(
        "/model-presets/presets/deepseek-default",
        json={"api_protocol": "responses"},
        headers=_auth(),
    )
    assert ok.status_code == 200
    saved = yaml.safe_load(temp_cfg.read_text(encoding="utf-8"))
    assert saved["model_presets"]["presets"]["deepseek-default"]["api_protocol"] == "responses"

    anthropic = client.put(
        "/model-presets/presets/deepseek-default",
        json={"api_protocol": "anthropic_messages", "anthropic_auth_mode": "bearer"},
        headers=_auth(),
    )
    assert anthropic.status_code == 200
    saved = yaml.safe_load(temp_cfg.read_text(encoding="utf-8"))
    preset = saved["model_presets"]["presets"]["deepseek-default"]
    assert preset["api_protocol"] == "anthropic_messages"
    assert preset["anthropic_auth_mode"] == "bearer"

    bad = client.put(
        "/model-presets/presets/deepseek-default",
        json={"api_protocol": "inferred"},
        headers=_auth(),
    )
    assert bad.status_code == 422

    bad_auth = client.put(
        "/model-presets/presets/deepseek-default",
        json={"anthropic_auth_mode": "basic"},
        headers=_auth(),
    )
    assert bad_auth.status_code == 422


def test_put_preset_legacy_mode_rejected(admin_client):
    client, temp_cfg = admin_client
    _write_cfg(temp_cfg, legacy=True)

    resp = client.put(
        "/model-presets/presets/new-one",
        json={"provider_kind": "openai", "model": "gpt-4"},
        headers=_auth(),
    )
    assert resp.status_code == 400


# ── DELETE /model-presets/presets/{name} ───────────────────────────────────────

def test_delete_unreferenced_preset_succeeds(admin_client):
    client, temp_cfg = admin_client
    mp = {
        **_BASE_MODEL_PRESETS,
        "presets": {
            **_BASE_MODEL_PRESETS["presets"],
            "spare": {"provider_kind": "openai", "base_url": "", "api_key": "", "model": "gpt-4"},
        },
    }
    _write_cfg(temp_cfg, model_presets=mp)

    resp = client.delete("/model-presets/presets/spare", headers=_auth())
    assert resp.status_code == 200

    saved = yaml.safe_load(temp_cfg.read_text(encoding="utf-8"))
    assert "spare" not in saved["model_presets"]["presets"]


def test_delete_nonexistent_preset_404(admin_client):
    client, temp_cfg = admin_client
    _write_cfg(temp_cfg)

    resp = client.delete("/model-presets/presets/ghost", headers=_auth())
    assert resp.status_code == 404


def test_delete_last_remaining_preset_409(admin_client):
    client, temp_cfg = admin_client
    _write_cfg(temp_cfg)  # only 1 preset: deepseek-default

    resp = client.delete("/model-presets/presets/deepseek-default", headers=_auth())
    assert resp.status_code == 409


def test_delete_referenced_preset_409(admin_client):
    client, temp_cfg = admin_client
    mp = {
        **_BASE_MODEL_PRESETS,
        "presets": {
            **_BASE_MODEL_PRESETS["presets"],
            "spare": {"provider_kind": "openai", "base_url": "", "api_key": "", "model": "gpt-4"},
        },
    }
    _write_cfg(temp_cfg, model_presets=mp)  # routing_profiles.default.chat -> deepseek-default

    resp = client.delete("/model-presets/presets/deepseek-default", headers=_auth())
    assert resp.status_code == 409
    assert "default.chat" in resp.json()["detail"]

    saved = yaml.safe_load(temp_cfg.read_text(encoding="utf-8"))
    assert "deepseek-default" in saved["model_presets"]["presets"]


# ── PUT /model-presets/routing-profiles/{name} ─────────────────────────────────

def test_put_routing_profile_creates_new(admin_client):
    client, temp_cfg = admin_client
    _write_cfg(temp_cfg)

    resp = client.put(
        "/model-presets/routing-profiles/claude-main",
        json={"chat": "deepseek-default"},
        headers=_auth(),
    )
    assert resp.status_code == 200

    saved = yaml.safe_load(temp_cfg.read_text(encoding="utf-8"))
    assert saved["model_presets"]["routing_profiles"]["claude-main"] == {"chat": "deepseek-default"}
    # existing profile untouched
    assert saved["model_presets"]["routing_profiles"]["default"]["chat"] == "deepseek-default"


def test_put_routing_profile_partial_merge(admin_client):
    client, temp_cfg = admin_client
    _write_cfg(temp_cfg)

    resp = client.put(
        "/model-presets/routing-profiles/default",
        json={"summary": "deepseek-default"},
        headers=_auth(),
    )
    assert resp.status_code == 200

    saved = yaml.safe_load(temp_cfg.read_text(encoding="utf-8"))
    profile = saved["model_presets"]["routing_profiles"]["default"]
    assert profile["summary"] == "deepseek-default"
    assert profile["chat"] == "deepseek-default"
    assert profile["probe"] == "deepseek-default"


def test_put_routing_profile_unknown_preset_rejected(admin_client):
    client, temp_cfg = admin_client
    _write_cfg(temp_cfg)

    resp = client.put(
        "/model-presets/routing-profiles/default",
        json={"chat": "does-not-exist"},
        headers=_auth(),
    )
    assert resp.status_code == 422

    saved = yaml.safe_load(temp_cfg.read_text(encoding="utf-8"))
    assert saved["model_presets"]["routing_profiles"]["default"]["chat"] == "deepseek-default"


def test_put_routing_profile_empty_body_rejected(admin_client):
    client, temp_cfg = admin_client
    _write_cfg(temp_cfg)

    resp = client.put("/model-presets/routing-profiles/default", json={}, headers=_auth())
    assert resp.status_code == 422


# ── POST /model-presets/presets/{name}/test ────────────────────────────────────

def _fake_model_client(model="deepseek-chat"):
    fake = MagicMock()
    fake.model = model
    fake.client = MagicMock()
    fake.client.close = AsyncMock()
    return fake


def test_connectivity_test_success(monkeypatch):
    import admin.routers.settings_llm as sl
    monkeypatch.setattr("admin.auth.get_admin_secret", lambda: VALID_TOKEN)

    fake_client = _fake_model_client()
    fake_response = MagicMock()
    fake_response.choices = [MagicMock(message=MagicMock(content="pong"))]
    fake_client.client.chat.completions.create = AsyncMock(return_value=fake_response)

    with patch("core.model_registry.build_client_for_preset", return_value=fake_client):
        app = FastAPI()
        app.include_router(sl.router)
        client = TestClient(app)
        resp = client.post("/model-presets/presets/deepseek-default/test", headers=_auth())

    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["model"] == "deepseek-chat"
    assert isinstance(data["latency_ms"], (int, float))
    assert data["reply_preview"] == "pong"
    fake_client.client.close.assert_awaited_once()


def test_connectivity_test_preset_not_found_404(monkeypatch):
    import admin.routers.settings_llm as sl
    monkeypatch.setattr("admin.auth.get_admin_secret", lambda: VALID_TOKEN)

    with patch("core.model_registry.build_client_for_preset", side_effect=ValueError("preset 'ghost' not found")):
        app = FastAPI()
        app.include_router(sl.router)
        client = TestClient(app)
        resp = client.post("/model-presets/presets/ghost/test", headers=_auth())

    assert resp.status_code == 404


def test_connectivity_test_reports_error_without_raising(monkeypatch):
    import admin.routers.settings_llm as sl
    monkeypatch.setattr("admin.auth.get_admin_secret", lambda: VALID_TOKEN)

    fake_client = _fake_model_client()
    fake_client.client.chat.completions.create = AsyncMock(side_effect=RuntimeError("connection refused"))

    with patch("core.model_registry.build_client_for_preset", return_value=fake_client):
        app = FastAPI()
        app.include_router(sl.router)
        client = TestClient(app)
        resp = client.post("/model-presets/presets/deepseek-default/test", headers=_auth())

    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is False
    assert "connection refused" in data["error"]
    fake_client.client.close.assert_awaited_once()


def test_no_token_rejected_on_all_new_endpoints(admin_client):
    client, temp_cfg = admin_client
    _write_cfg(temp_cfg)

    assert client.put("/model-presets/presets/x", json={"provider_kind": "openai", "model": "x"}).status_code in (401, 403)
    assert client.delete("/model-presets/presets/deepseek-default").status_code in (401, 403)
    assert client.put("/model-presets/routing-profiles/default", json={"chat": "deepseek-default"}).status_code in (401, 403)
    assert client.post("/model-presets/presets/deepseek-default/test").status_code in (401, 403)
