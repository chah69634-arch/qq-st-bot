"""Tool-loop settings limits exposed by the admin control plane."""

from __future__ import annotations

import asyncio

import yaml

from admin.routers import settings_tool_loop as mod


def test_total_timeout_accepts_hardware_sequence_budget(tmp_path, monkeypatch):
    path = tmp_path / "config.yaml"
    path.write_text("tool_loop: {}\n", encoding="utf-8")
    monkeypatch.setattr(mod, "CONFIG_FILE", path)
    monkeypatch.setattr(mod, "_chat_preset_supports_fc", lambda: True)
    monkeypatch.setattr("core.config_loader.reload_config", lambda: {})

    result = asyncio.run(mod.update_tool_loop(
        mod.ToolLoopUpdate(total_timeout_s=999), auth=None,
    ))

    assert result["tool_loop"]["total_timeout_s"] == 720
    assert yaml.safe_load(path.read_text(encoding="utf-8"))["tool_loop"]["total_timeout_s"] == 720
