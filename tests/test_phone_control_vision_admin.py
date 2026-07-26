"""Brief 123: admin control of the fixed phone-control vision override slot."""
from __future__ import annotations

import asyncio

import yaml
from unittest.mock import patch

from admin.routers import settings_llm as mod
from core.phone_control.vision_client import get_phone_control_vision_config


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
    return read


def test_phone_control_override_writes_only_explicit_fields_and_updates_effective_model(tmp_path, monkeypatch):
    path = _write(tmp_path, "vision:\n  enabled: true\n  base_url: https://vision.example/v1\n  api_key: inherited-key\n  model: general-model\n")
    read = _patch_config(monkeypatch, path)

    result = asyncio.run(mod.update_phone_control_vision_params(
        mod.PhoneControlVisionParamsUpdate(model="phone-model"), _auth=None,
    ))

    assert result["phone_control_vision"] == {
        "enabled": None, "api_key": "", "model": "phone-model", "base_url": "",
    }
    cfg = read()
    assert cfg["phone_control_vision"] == {"model": "phone-model"}
    with patch("core.config_loader.get_config", return_value=cfg):
        effective = get_phone_control_vision_config()
    assert effective["model"] == "phone-model"
    assert effective["base_url"] == "https://vision.example/v1"
    assert effective["api_key"] == "inherited-key"


def test_phone_control_blank_fields_remove_override_and_restore_inheritance(tmp_path, monkeypatch):
    path = _write(tmp_path, "vision:\n  enabled: true\n  base_url: https://vision.example/v1\n  model: general-model\nphone_control_vision:\n  enabled: false\n  base_url: https://phone.example/v1\n  model: phone-model\n")
    read = _patch_config(monkeypatch, path)

    result = asyncio.run(mod.update_phone_control_vision_params(
        mod.PhoneControlVisionParamsUpdate(enabled=None, api_key="", base_url="", model=""), _auth=None,
    ))

    assert result["phone_control_vision"] == {
        "enabled": None, "api_key": "", "model": "", "base_url": "",
    }
    cfg = read()
    assert "phone_control_vision" not in cfg
    with patch("core.config_loader.get_config", return_value=cfg):
        assert get_phone_control_vision_config()["model"] == "general-model"


def test_phone_control_false_enabled_is_a_real_override_not_an_empty_value():
    cfg = {
        "vision": {"enabled": True, "base_url": "https://vision.example", "model": "general-model"},
        "phone_control_vision": {"enabled": False, "model": "phone-model"},
    }
    with patch("core.config_loader.get_config", return_value=cfg):
        effective = get_phone_control_vision_config()
    assert effective["enabled"] is False
    assert effective["model"] == "phone-model"
