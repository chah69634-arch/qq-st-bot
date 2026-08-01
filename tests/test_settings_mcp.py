"""Brief 110: MCP 管理 API 不接真实网络，覆盖导入、白名单与热重载。"""
from __future__ import annotations

import asyncio

import pytest
import yaml
from fastapi import HTTPException
from pydantic import ValidationError

from admin.routers import settings_mcp as mod


def _write(tmp_path, text: str):
    path = tmp_path / "config.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def _patch_config(monkeypatch, path):
    monkeypatch.setattr(mod, "CONFIG_FILE", path)
    read = lambda: yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    monkeypatch.setattr(mod, "get_config", read)
    from core import config_loader
    monkeypatch.setattr(config_loader, "reload_config", lambda: read())


def _draft(**overrides):
    data = {
        "name": "cedar_toy",
        "url": "https://example.test/mcp",
        "headers": {"Authorization": "Bearer ${CEDAR_TOY_TOKEN}"},
        "allow_tools": ["toy_status"],
    }
    data.update(overrides)
    return mod.McpServerDraft(**data)


def test_remote_transport_validation_defaults_to_streamable_http_and_accepts_sse():
    assert mod._validate_draft(_draft())["transport"] == "streamable-http"
    assert mod._validate_draft(_draft())["use_proxy"] is False
    assert mod._validate_draft(_draft(transport="sse"))["transport"] == "sse"


def test_remote_transport_validation_keeps_legacy_http_alias_and_rejects_unknown():
    assert mod._validate_draft(_draft(transport="http"))["transport"] == "http"
    invalid = _draft().model_dump()
    invalid["transport"] = "websocket"
    with pytest.raises(ValidationError):
        mod.McpServerDraft(**invalid)


def test_import_tests_before_write_and_hot_reloads(tmp_path, monkeypatch):
    """Brief 115 根治：MCP 连接生命周期已改成专属常驻 task 持有、管理面只发信号，
    不再跨 task 直接碰 AsyncExitStack，导入接口的热重载可以安全恢复。"""
    path = _write(tmp_path, "mcp_servers:\n  enabled: true\n  servers: []\n")
    _patch_config(monkeypatch, path)
    from core import mcp_client
    calls = []

    async def probe(cfg):
        calls.append(("probe", cfg))
        return [{"name": "toy_status", "description": "status"}]

    async def reload(name):
        calls.append(("reload", name))
        return True

    monkeypatch.setattr(mcp_client, "test_server_config", probe)
    monkeypatch.setattr(mcp_client, "reload_server_from_config", reload)
    monkeypatch.setattr(mcp_client, "server_runtime", lambda name: {"connected": True, "tools": []})

    result = asyncio.run(mod.import_mcp_server(_draft(), _auth=None))

    assert result["tools"][0]["name"] == "toy_status"
    assert result["server"]["headers"]["Authorization"] == "Bearer ${CEDAR_TOY_TOKEN}"
    assert calls == [("probe", mod._validate_draft(_draft())), ("reload", "cedar_toy")]
    assert "重启" not in result["message"]
    cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert cfg["mcp_servers"]["servers"][0]["headers"]["Authorization"] == "Bearer ${CEDAR_TOY_TOKEN}"


def test_import_rejects_unknown_whitelist_without_writing(tmp_path, monkeypatch):
    path = _write(tmp_path, "mcp_servers:\n  enabled: false\n  servers: []\n")
    before = path.read_text(encoding="utf-8")
    _patch_config(monkeypatch, path)
    from core import mcp_client

    async def probe(_cfg):
        return [{"name": "known", "description": ""}]

    monkeypatch.setattr(mcp_client, "test_server_config", probe)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(mod.import_mcp_server(_draft(allow_tools=["unknown"]), _auth=None))
    assert exc.value.status_code == 422
    assert path.read_text(encoding="utf-8") == before


def test_reimport_preserves_existing_explicit_policy_and_marks_new_tool_pending(tmp_path, monkeypatch):
    path = _write(
        tmp_path,
        "mcp_servers:\n  enabled: true\n  require_local_policy: true\n  servers:\n"
        "    - name: cedar_toy\n      transport: http\n      url: https://old.test/mcp\n"
        "      allow_tools: [toy_status]\n      tool_policy:\n"
        "        toy_status: {effect: read}\n",
    )
    _patch_config(monkeypatch, path)
    from core import mcp_client

    async def probe(_cfg):
        return [
            {"name": "toy_status", "description": "status"},
            {"name": "send_message", "description": "send a message"},
        ]

    async def reload(_name):
        return True

    monkeypatch.setattr(mcp_client, "test_server_config", probe)
    monkeypatch.setattr(mcp_client, "reload_server_from_config", reload)
    monkeypatch.setattr(mcp_client, "server_runtime", lambda _name: {
        "connected": True,
        "tools": [
            {"name": "toy_status", "description": "status"},
            {"name": "send_message", "description": "send a message"},
        ],
    })
    result = asyncio.run(mod.import_mcp_server(
        _draft(allow_tools=["toy_status", "send_message"]), _auth=None,
    ))

    states = {item["name"]: item for item in result["server"]["tool_states"]}
    assert states["toy_status"]["policy_status"] == "confirmed"
    assert states["send_message"]["policy_status"] == "pending_confirmation"
    stored = yaml.safe_load(path.read_text(encoding="utf-8"))["mcp_servers"]["servers"][0]
    assert stored["tool_policy"] == {"toy_status": {"effect": "read"}}


def test_existing_explicit_policy_is_read_as_confirmed_without_config_migration(tmp_path, monkeypatch):
    path = _write(
        tmp_path,
        "mcp_servers:\n  enabled: true\n  require_local_policy: true\n  servers:\n"
        "    - name: cedar_toy\n      transport: http\n      url: https://example.test/mcp\n"
        "      allow_tools: [toy_status]\n      tool_policy:\n"
        "        toy_status: {effect: read}\n",
    )
    before = path.read_text(encoding="utf-8")
    _patch_config(monkeypatch, path)
    from core import mcp_client

    monkeypatch.setattr(mcp_client, "server_runtime", lambda _name: {
        "connected": True,
        "tools": [{"name": "toy_status", "description": "status"}],
    })
    result = asyncio.run(mod.get_mcp_settings(_auth=None))

    state = result["servers"][0]["tool_states"][0]
    assert state["policy_status"] == "confirmed"
    assert state["policy"] == {"effect": "read"}
    assert path.read_text(encoding="utf-8") == before


def test_strict_import_keeps_new_allowlist_tools_pending_confirmation(tmp_path, monkeypatch):
    path = _write(tmp_path, "mcp_servers:\n  enabled: true\n  require_local_policy: true\n  servers: []\n")
    _patch_config(monkeypatch, path)
    from core import mcp_client

    async def probe(_cfg):
        return [{"name": "toy_status", "description": "status"}]

    async def reload(_name):
        return True

    monkeypatch.setattr(mcp_client, "test_server_config", probe)
    monkeypatch.setattr(mcp_client, "reload_server_from_config", reload)
    monkeypatch.setattr(mcp_client, "server_runtime", lambda _name: {
        "connected": True,
        "tools": [{"name": "toy_status", "description": "status"}],
    })
    result = asyncio.run(mod.import_mcp_server(_draft(), _auth=None))

    assert result["reload_status"] == "reloaded"
    assert result["server"]["tool_states"][0]["policy_status"] == "pending_confirmation"
    stored = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert "tool_policy" not in stored["mcp_servers"]["servers"][0]


def test_global_toggle_writes_config_and_hot_syncs(tmp_path, monkeypatch):
    """Brief 115 根治：总开关热同步已恢复，sync_mcp_servers 只发信号给专属常驻 task。"""
    path = _write(tmp_path, "mcp_servers:\n  enabled: false\n  servers: []\n")
    _patch_config(monkeypatch, path)
    from core import mcp_client
    calls = []

    async def sync():
        calls.append("sync")

    monkeypatch.setattr(mcp_client, "sync_mcp_servers", sync)
    result = asyncio.run(mod.update_mcp_settings(mod.McpSettingsUpdate(enabled=True), _auth=None))
    assert result["enabled"] is True
    assert calls == ["sync"]
    assert "重启" not in result["message"]
    cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert cfg["mcp_servers"]["enabled"] is True


def test_update_server_whitelist_writes_config_and_hot_reloads(tmp_path, monkeypatch):
    """Brief 115 根治：单 server 更新的热重载已恢复（同上）。"""
    path = _write(tmp_path, "mcp_servers:\n  enabled: true\n  servers:\n    - name: cedar_toy\n      transport: http\n      url: https://example.test/mcp\n      allow_tools: []\n")
    _patch_config(monkeypatch, path)
    from core import mcp_client
    calls = []

    async def reload(name):
        calls.append(name)
        return True

    monkeypatch.setattr(mcp_client, "reload_server_from_config", reload)
    monkeypatch.setattr(mcp_client, "server_runtime", lambda name: {"connected": False, "tools": []})
    result = asyncio.run(mod.update_mcp_server(
        "cedar_toy", mod.McpServerUpdate(allow_tools=["toy_status"], use_proxy=True), _auth=None,
    ))
    assert result["server"]["allow_tools"] == ["toy_status"]
    assert result["server"]["use_proxy"] is True
    assert calls == ["cedar_toy"]
    assert "重启" not in result["message"]
    assert yaml.safe_load(path.read_text(encoding="utf-8"))["mcp_servers"]["servers"][0]["use_proxy"] is True


def test_update_server_persists_per_tool_timeout_and_returns_it(tmp_path, monkeypatch):
    path = _write(tmp_path, "mcp_servers:\n  enabled: true\n  servers:\n    - name: cedar_toy\n      transport: http\n      url: https://example.test/mcp\n")
    _patch_config(monkeypatch, path)
    from core import mcp_client

    async def reload(_name):
        return True

    monkeypatch.setattr(mcp_client, "reload_server_from_config", reload)
    monkeypatch.setattr(mcp_client, "server_runtime", lambda _name: {"connected": False, "tools": []})
    result = asyncio.run(mod.update_mcp_server(
        "cedar_toy", mod.McpServerUpdate(tool_timeouts_s={"hardware_sequence": 60}), _auth=None,
    ))

    assert result["server"]["tool_timeouts_s"] == {"hardware_sequence": 60.0}
    stored = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert stored["mcp_servers"]["servers"][0]["tool_timeouts_s"] == {"hardware_sequence": 60.0}


def test_update_server_reports_restart_when_owner_reload_fails(tmp_path, monkeypatch):
    path = _write(tmp_path, "mcp_servers:\n  enabled: true\n  servers:\n    - name: cedar_toy\n      transport: http\n      url: https://example.test/mcp\n      allow_tools: [toy_status]\n")
    _patch_config(monkeypatch, path)
    from core import mcp_client

    async def reload(_name):
        return False

    monkeypatch.setattr(mcp_client, "reload_server_from_config", reload)
    monkeypatch.setattr(mcp_client, "server_runtime", lambda _name: {"connected": False, "tools": []})
    result = asyncio.run(mod.update_mcp_server(
        "cedar_toy", mod.McpServerUpdate(enabled=False), _auth=None,
    ))
    assert result["reload_status"] == "restart_required"
    assert "重启" in result["message"]


def test_strict_policy_whitelist_update_preserves_confirmed_entries_and_leaves_new_tool_pending(tmp_path, monkeypatch):
    path = _write(
        tmp_path,
        "mcp_servers:\n  enabled: true\n  require_local_policy: true\n  servers:\n"
        "    - name: cedar_toy\n      transport: http\n      url: https://example.test/mcp\n"
        "      allow_tools: [toy_status]\n      tool_policy:\n"
        "        toy_status: {effect: read}\n",
    )
    _patch_config(monkeypatch, path)
    from core import mcp_client

    async def reload(name):
        assert name == "cedar_toy"
        return True

    monkeypatch.setattr(mcp_client, "reload_server_from_config", reload)
    monkeypatch.setattr(mcp_client, "server_runtime", lambda _name: {
        "connected": True,
        "tools": [
            {"name": "toy_status", "description": "status"},
            {"name": "delete_thread", "description": "delete thread"},
        ],
    })
    result = asyncio.run(mod.update_mcp_server(
        "cedar_toy", mod.McpServerUpdate(allow_tools=["toy_status", "delete_thread"]), _auth=None,
    ))
    states = {item["name"]: item for item in result["server"]["tool_states"]}
    assert states["toy_status"]["policy_status"] == "confirmed"
    assert states["delete_thread"]["policy_status"] == "pending_confirmation"
    stored = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert stored["mcp_servers"]["servers"][0]["tool_policy"] == {"toy_status": {"effect": "read"}}


def test_strict_policy_accepts_complete_whitelist_and_policy(tmp_path, monkeypatch):
    path = _write(
        tmp_path,
        "mcp_servers:\n  enabled: true\n  require_local_policy: true\n  servers:\n"
        "    - name: cedar_toy\n      transport: http\n      url: https://example.test/mcp\n"
        "      allow_tools: [toy_status]\n      tool_policy:\n"
        "        toy_status: {effect: read}\n",
    )
    _patch_config(monkeypatch, path)
    from core import mcp_client
    calls = []

    async def reload(name):
        calls.append(name)
        return True

    monkeypatch.setattr(mcp_client, "reload_server_from_config", reload)
    monkeypatch.setattr(mcp_client, "server_runtime", lambda name: {"connected": True, "tools": []})
    result = asyncio.run(mod.update_mcp_server(
        "cedar_toy",
        mod.McpServerUpdate(
            allow_tools=["toy_status", "delete_thread"],
            tool_policy={
                "toy_status": mod.McpToolPolicy(effect="read"),
                "delete_thread": mod.McpToolPolicy(effect="write"),
            },
        ),
        _auth=None,
    ))

    assert result["server"]["tool_policy"]["delete_thread"] == {"effect": "write"}
    assert calls == ["cedar_toy"]


def test_selecting_named_tool_preset_updates_runtime_allowlist(tmp_path, monkeypatch):
    path = _write(tmp_path, "mcp_servers:\n  enabled: true\n  servers:\n    - name: cedar_toy\n      transport: http\n      url: https://example.test/mcp\n      allow_tools: [toy_status]\n      tool_presets:\n        - name: 只读\n          tools: [toy_status]\n        - name: 对局\n          tools: [toy_status, play]\n")
    _patch_config(monkeypatch, path)
    from core import mcp_client
    calls = []

    async def reload(name):
        calls.append(name)

    monkeypatch.setattr(mcp_client, "reload_server_from_config", reload)
    monkeypatch.setattr(mcp_client, "server_runtime", lambda name: {"connected": True, "tools": []})
    result = asyncio.run(mod.update_mcp_server(
        "cedar_toy", mod.McpServerUpdate(active_tool_preset="对局"), _auth=None,
    ))

    assert result["server"]["active_tool_preset"] == "对局"
    assert result["server"]["allow_tools"] == ["toy_status", "play"]
    assert calls == ["cedar_toy"]


def test_delete_server_removes_config_and_syncs_its_runtime(tmp_path, monkeypatch):
    path = _write(tmp_path, "mcp_servers:\n  enabled: true\n  servers:\n    - name: cedar_toy\n      transport: http\n      url: https://example.test/mcp\n    - name: keep_me\n      transport: http\n      url: https://example.test/keep\n")
    _patch_config(monkeypatch, path)
    from core import mcp_client

    calls = []

    async def sync():
        calls.append("sync")

    monkeypatch.setattr(mcp_client, "sync_mcp_servers", sync)
    result = asyncio.run(mod.delete_mcp_server("cedar_toy", _auth=None))

    assert result == {"message": "MCP server 已删除并断开", "deleted": "cedar_toy"}
    assert calls == ["sync"]
    cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert [item["name"] for item in cfg["mcp_servers"]["servers"]] == ["keep_me"]


def test_delete_missing_server_returns_not_found(tmp_path, monkeypatch):
    path = _write(tmp_path, "mcp_servers:\n  enabled: true\n  servers: []\n")
    _patch_config(monkeypatch, path)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(mod.delete_mcp_server("missing", _auth=None))

    assert exc.value.status_code == 404
