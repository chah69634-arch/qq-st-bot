import asyncio

import pytest
import yaml


def test_idempotent_owner_turn_passes_stable_ingress_id(sandbox, monkeypatch):
    from core import owner_turn_service as service

    captured = {}

    async def executor(_message, _channel, **kwargs):
        captured.update(kwargs)
        return {"reply": "ok", "turn_id": "turn-stable"}

    monkeypatch.setattr(
        service,
        "_project_canonical_result",
        lambda _turn_id: {"reply": "ok", "turn_id": "turn-stable"},
    )
    status, result = asyncio.run(service.execute_idempotent_owner_turn(
        client_turn_id="client-stable",
        message="hello",
        reply_to=None,
        upload_ids=[],
        context=service.owner_input_context("identity-boundary-test"),
        executor=executor,
    ))

    assert status == "completed"
    assert result["turn_id"] == "turn-stable"
    assert captured["ingress_event_id"] == "owner:identity-boundary-test:client-stable"
    assert captured["ingress_dedupe_key"] == captured["ingress_event_id"]


def test_observer_cannot_be_enabled_when_ledger_startup_is_not_ready(tmp_path, monkeypatch):
    from admin.routers import settings_feature_flags as mod
    from fastapi import HTTPException
    from core import config_loader

    path = tmp_path / "config.yaml"
    path.write_text("event_context_observer:\n  mode: disabled\n", encoding="utf-8")
    monkeypatch.setattr(mod, "CONFIG_FILE", path)
    monkeypatch.setattr(mod, "read_config_file", lambda _path: yaml.safe_load(path.read_text(encoding="utf-8")))
    monkeypatch.setattr(mod, "get_config", lambda: yaml.safe_load(path.read_text(encoding="utf-8")))
    monkeypatch.setattr(config_loader, "get_config", lambda: yaml.safe_load(path.read_text(encoding="utf-8")))
    monkeypatch.setattr(config_loader, "reload_config", lambda: None)
    monkeypatch.setattr(
        "core.memory.event_store.initialize_existing_ledgers",
        lambda: {"status": "attention", "failed": 1, "truncated": False},
    )

    with pytest.raises(HTTPException) as exc:
        asyncio.run(mod.update_event_context_observer_settings(
            mod.EventContextObserverUpdate(mode="observe"), auth=None,
        ))
    assert exc.value.status_code == 503
    assert exc.value.detail["code"] == "event_ledger_not_ready"
    assert yaml.safe_load(path.read_text(encoding="utf-8"))["event_context_observer"]["mode"] == "disabled"


def test_observer_enable_runs_startup_readiness_check(tmp_path, monkeypatch):
    from admin.routers import settings_feature_flags as mod
    from core import config_loader

    path = tmp_path / "config.yaml"
    path.write_text("event_context_observer:\n  mode: disabled\n", encoding="utf-8")
    monkeypatch.setattr(mod, "CONFIG_FILE", path)
    monkeypatch.setattr(mod, "read_config_file", lambda _path: yaml.safe_load(path.read_text(encoding="utf-8")))
    monkeypatch.setattr(mod, "get_config", lambda: yaml.safe_load(path.read_text(encoding="utf-8")))
    monkeypatch.setattr(config_loader, "get_config", lambda: yaml.safe_load(path.read_text(encoding="utf-8")))
    monkeypatch.setattr(config_loader, "reload_config", lambda: None)
    readiness = {"status": "ok", "discovered": 2, "healthy": 2, "failed": 0, "truncated": False}
    monkeypatch.setattr("core.memory.event_store.initialize_existing_ledgers", lambda: readiness)

    result = asyncio.run(mod.update_event_context_observer_settings(
        mod.EventContextObserverUpdate(mode="observe"), auth=None,
    ))
    assert result["desired"] == "observe"
    assert yaml.safe_load(path.read_text(encoding="utf-8"))["event_context_observer"]["mode"] == "observe"
