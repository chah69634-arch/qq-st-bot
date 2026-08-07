"""Release-audit contracts for the public first-run configuration."""
from __future__ import annotations

import json
from pathlib import Path

import yaml


def _template() -> dict:
    return yaml.safe_load(Path("config.example.yaml").read_text(encoding="utf-8")) or {}


def test_public_template_is_conservative_until_explicit_opt_in():
    cfg = _template()

    assert cfg["notify"]["enabled"] is False
    assert cfg["scheduler"]["enabled"] is False
    assert cfg["qq"]["enabled"] is False
    assert cfg["standalone_mode"] is False
    assert cfg["hardware"]["enabled"] is False
    assert cfg["hardware"]["intiface_opt_in"] is False
    assert cfg["mcp_servers"]["enabled"] is False
    assert all(not server.get("enabled", True) for server in cfg["mcp_servers"]["servers"])
    assert cfg["tool_loop"]["enabled"] is False
    assert cfg["fs_access"]["enabled"] is False


def test_public_template_disables_high_risk_tool_defaults():
    tools = _template()["tools"]
    for name in (
        "device_shutdown",
        "device_sleep",
        "toy_vibrate",
        "toy_stop",
        "toy_pattern",
        "write_toy_file",
    ):
        assert tools.get(name, {}).get("enabled", False) is False, name


def test_clean_install_has_a_loadable_neutral_character_seed():
    cfg = _template()
    char_id = str(cfg["character"]["default"])
    card = Path("bundled/characters") / char_id / "card.json"
    assert card.is_file(), f"missing bundled character seed for {char_id!r}"
    payload = json.loads(card.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    assert str(payload.get("name") or "").strip()


def test_cold_start_runbook_documents_recovery_and_readiness_contract():
    text = Path("docs/v1-cold-start-single-user-deployment.md").read_text(encoding="utf-8")
    for marker in (
        "## Clean install",
        "## Conservative defaults",
        "## Readiness checklist",
        "## v0.2.2 migration",
        "backup-state create",
        "backup-state restore",
        "restart_miss_policy: skip",
        "## External MCP failure behavior",
    ):
        assert marker in text
