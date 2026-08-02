"""Admin tool-control API: registry observation and model-specific exposure."""
from unittest.mock import patch

import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient

VALID_TOKEN = "tools-test-secret"


def _auth():
    return {"Authorization": f"Bearer {VALID_TOKEN}"}


def _config():
    return {
        "tools": {},
        "tool_loop": {"tool_presets": []},
        "model_presets": {
            "presets": {
                "claude-pig": {"provider_kind": "anthropic_compat", "model": "claude"},
                "gpt": {"provider_kind": "openai", "model": "gpt"},
            },
        },
    }


def test_tool_control_saves_preset_binding_and_builtin_execution(tmp_path, monkeypatch):
    import admin.routers.settings_tools as st

    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(_config(), allow_unicode=True), encoding="utf-8")
    monkeypatch.setattr(st, "CONFIG_FILE", path)
    monkeypatch.setattr("admin.auth.get_admin_secret", lambda: VALID_TOKEN)
    monkeypatch.setattr(st, "get_config", lambda: yaml.safe_load(path.read_text(encoding="utf-8")))

    with patch("core.config_loader.reload_config", return_value=None):
        app = FastAPI()
        app.include_router(st.router)
        client = TestClient(app)
        discovered = client.get("/settings/tools", headers=_auth())
        assert discovered.status_code == 200
        builtin = discovered.json()["tools"][0]["name"]

        updated = client.put(
            "/settings/tools",
            headers=_auth(),
            json={
                "tool_presets": [{"name": "claude-minimal", "tools": [builtin]}],
                "model_bindings": {"claude-pig": "claude-minimal"},
                "execution_enabled": {builtin: False},
            },
        )
        assert updated.status_code == 200
        saved = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert saved["tool_loop"]["tool_presets"] == [{"name": "claude-minimal", "tools": [builtin]}]
        assert saved["model_presets"]["presets"]["claude-pig"]["tool_preset"] == "claude-minimal"
        assert saved["tools"][builtin]["enabled"] is False


def test_deleting_tool_preset_clears_existing_model_bindings(tmp_path, monkeypatch):
    import admin.routers.settings_tools as st

    cfg = _config()
    cfg["tool_loop"]["tool_presets"] = [{"name": "old", "tools": ["get_time"]}]
    cfg["model_presets"]["presets"]["claude-pig"]["tool_preset"] = "old"
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    monkeypatch.setattr(st, "CONFIG_FILE", path)
    monkeypatch.setattr("admin.auth.get_admin_secret", lambda: VALID_TOKEN)
    monkeypatch.setattr(st, "get_config", lambda: yaml.safe_load(path.read_text(encoding="utf-8")))

    with patch("core.config_loader.reload_config", return_value=None):
        app = FastAPI()
        app.include_router(st.router)
        response = TestClient(app).put("/settings/tools", headers=_auth(), json={"tool_presets": []})

    assert response.status_code == 200
    saved = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert "tool_preset" not in saved["model_presets"]["presets"]["claude-pig"]


def test_tool_page_hides_transient_mcp_tools_and_reports_only_global_state(tmp_path, monkeypatch):
    import admin.routers.settings_tools as st
    from core import tool_dispatcher

    cfg = _config()
    cfg["mcp_servers"] = {"enabled": True}
    cfg["tool_loop"]["tool_presets"] = [{"name": "mixed", "tools": ["builtin", "dynamic"]}]
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    monkeypatch.setattr(st, "CONFIG_FILE", path)
    monkeypatch.setattr("admin.auth.get_admin_secret", lambda: VALID_TOKEN)
    monkeypatch.setattr(st, "get_config", lambda: yaml.safe_load(path.read_text(encoding="utf-8")))
    monkeypatch.setattr(tool_dispatcher, "_TOOL_REGISTRY", {
        "builtin": {"category": "info", "description": "built in"},
        "dynamic": {"category": "mcp", "description": "transient"},
    })

    app = FastAPI()
    app.include_router(st.router)
    result = TestClient(app).get("/settings/tools", headers=_auth()).json()

    assert result["mcp_enabled"] is True
    assert [tool["name"] for tool in result["tools"]] == ["builtin"]
    assert result["tool_presets"] == [{"name": "mixed", "tools": ["builtin"]}]
