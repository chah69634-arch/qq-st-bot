from __future__ import annotations

import json
from pathlib import Path

import pytest

from core import backup_state as backup
from core.no_outbound import OutboundAttempted, recovery_no_outbound


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _snapshot(tmp_path: Path) -> tuple[Path, Path]:
    install = tmp_path / "install"
    _write(install / "VERSION", "v1.0.0")
    _write(install / "config.yaml", "character:\n  default: default\n")
    _write(install / "data" / "layout_version.json", json.dumps({"product_baseline":"v1","data_layout_schema_version":1,"first_initialized_version":"v1.0.0"}))
    _write(install / "data" / "runtime" / "memory" / "c" / "u" / "history.json", "[]")
    _write(install / "userdata" / "characters" / "cards" / "x.json", "{}")
    backup_dir = tmp_path / "backups" / "snapshot"
    backup_dir.parent.mkdir()
    backup.create_snapshot(install, backup_dir, protection_mode="protected_volume", get_service_state=lambda _: backup.ServiceState.OFFLINE)
    return install, backup_dir


def test_restore_round_trip_to_missing_and_empty_targets(tmp_path: Path):
    install, snapshot = _snapshot(tmp_path)
    target = tmp_path / "restored"
    result = backup.restore_snapshot(install, snapshot, target, startup_check=False)
    assert result["ok"] and (target / "config.yaml").is_file()
    assert (target / ".presencekit-recovery" / "recovery-report.json").is_file()

    empty = tmp_path / "empty"
    empty.mkdir()
    assert backup.restore_snapshot(install, snapshot, empty, startup_check=False)["ok"]


@pytest.mark.parametrize("target_kind, code", [("nonempty", "target_not_empty"), ("live", "target_is_live_path"), ("data", "target_is_live_path"), ("inside_snapshot", "target_is_live_path")])
def test_restore_rejects_unsafe_targets(tmp_path: Path, target_kind: str, code: str):
    install, snapshot = _snapshot(tmp_path)
    target = {"nonempty": tmp_path / "occupied", "live": install, "data": install / "data", "inside_snapshot": snapshot / "child"}[target_kind]
    if target_kind == "nonempty":
        target.mkdir(); _write(target / "x", "x")
    with pytest.raises(backup.BackupError) as raised:
        backup.restore_snapshot(install, snapshot, target, startup_check=False)
    assert raised.value.code == code


def test_restore_rejects_tampering_collision_and_limits(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    install, snapshot = _snapshot(tmp_path)
    _write(snapshot / "unexpected", "x")
    with pytest.raises(backup.BackupError) as raised:
        backup.restore_snapshot(install, snapshot, tmp_path / "out", startup_check=False)
    assert raised.value.code == "backup_verify_failed"

    install, snapshot = _snapshot(tmp_path / "second")
    monkeypatch.setattr(backup, "MAX_RESTORE_FILES", 1)
    with pytest.raises(backup.BackupError) as raised:
        backup.restore_snapshot(install, snapshot, tmp_path / "second" / "out", startup_check=False)
    assert raised.value.code == "archive_limit_exceeded"


@pytest.mark.asyncio
async def test_no_outbound_guard_blocks_real_boundary_calls():
    from core.llm_client import chat
    from core.mcp_client import init_mcp_servers
    from core.hardware.buttplug_client import ensure_connected
    from core.qq_adapter import connect_and_listen
    from channels.registry import broadcast
    from core.scheduler.loop import start
    from core.tools.weather import get_weather
    from core.tools.web_search import search
    with recovery_no_outbound() as guard:
        for call in (chat([]), get_weather("x"), search("x"), init_mcp_servers(), ensure_connected(), connect_and_listen(), broadcast("x", "u")):
            with pytest.raises(OutboundAttempted):
                await call
        with pytest.raises(OutboundAttempted):
            start()
    assert guard.attempts == ["llm", "weather", "web_search", "mcp_init", "hardware_gateway", "qq_connect", "channel_fanout", "scheduler_start"]
