import asyncio
from pathlib import Path

import pytest
import yaml
from fastapi import HTTPException

from admin import config_control


def _read(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def test_write_config_file_is_atomic_and_persists(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("practice:\n  enabled: false\n", encoding="utf-8")

    config_control.write_config_file(path, {"practice": {"enabled": True}})

    assert _read(path) == {"practice": {"enabled": True}}
    assert not path.with_suffix(".yaml.tmp").exists()


def test_write_config_file_rejects_shadowed_local_key(tmp_path):
    path = tmp_path / "config.yaml"
    local_path = tmp_path / "config.local.yaml"
    path.write_text("model_presets:\n  active_routing: default\n", encoding="utf-8")
    local_path.write_text("model_presets:\n  active_routing: fixed\n", encoding="utf-8")

    with pytest.raises(HTTPException) as exc:
        config_control.write_config_file(path, {"model_presets": {"active_routing": "other"}})

    assert exc.value.status_code == 409
    assert "model_presets.active_routing" in str(exc.value.detail)
    assert _read(path)["model_presets"]["active_routing"] == "default"


def test_write_config_file_allows_unrelated_local_override(tmp_path):
    path = tmp_path / "config.yaml"
    local_path = tmp_path / "config.local.yaml"
    path.write_text("practice:\n  enabled: false\nproxy:\n  http: ''\n", encoding="utf-8")
    local_path.write_text("proxy:\n  http: http://local-proxy\n", encoding="utf-8")

    updated = _read(path)
    updated["practice"]["enabled"] = True
    config_control.write_config_file(path, updated)

    assert _read(path)["practice"]["enabled"] is True


def test_write_failure_keeps_original_config(tmp_path, monkeypatch):
    path = tmp_path / "config.yaml"
    path.write_text("practice:\n  enabled: false\n", encoding="utf-8")
    monkeypatch.setattr(config_control, "safe_write_text", lambda *_args, **_kwargs: False)

    with pytest.raises(HTTPException) as exc:
        config_control.write_config_file(path, {"practice": {"enabled": True}})

    assert exc.value.status_code == 500
    assert _read(path)["practice"]["enabled"] is False


def test_config_document_three_way_merge_preserves_concurrent_change(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("practice:\n  enabled: false\nproxy:\n  enabled: false\n", encoding="utf-8")
    first = config_control.read_config_file(path)
    second = config_control.read_config_file(path)
    first["practice"]["enabled"] = True
    second["proxy"]["enabled"] = True

    config_control.write_config_file(path, first)
    config_control.write_config_file(path, second)

    assert _read(path) == {
        "practice": {"enabled": True},
        "proxy": {"enabled": True},
    }


def test_settings_routers_do_not_write_config_directly():
    root = Path(__file__).parent.parent / "admin" / "routers"
    violations = []
    for path in root.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        manages_base_config = "config.yaml" in text and (
            'open(CONFIG_FILE, "w"' in text
            or 'CONFIG_FILE.open("w"' in text
            or 'open(path, "w"' in text and "scheduler" in path.name
        )
        if manages_base_config:
            violations.append(path.name)
    assert violations == []


def test_feature_flag_endpoint_surfaces_local_override_conflict(tmp_path, monkeypatch):
    from admin.routers import settings_feature_flags as flags

    path = tmp_path / "config.yaml"
    path.write_text("practice:\n  enabled: false\n", encoding="utf-8")
    path.with_name("config.local.yaml").write_text(
        "practice:\n  enabled: false\n", encoding="utf-8"
    )
    monkeypatch.setattr(flags, "CONFIG_FILE", path)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(flags.update_feature_flags(flags.FeatureFlagsUpdate(flags={"practice": True})))

    assert exc.value.status_code == 409
    assert _read(path)["practice"]["enabled"] is False


def test_model_routing_endpoint_does_not_report_shadowed_write_as_success(tmp_path, monkeypatch):
    from admin.routers import settings_llm

    path = tmp_path / "config.yaml"
    path.write_text(
        "model_presets:\n"
        "  active_routing: default\n"
        "  presets:\n"
        "    base: {provider_kind: openai}\n"
        "  routing_profiles:\n"
        "    default: {chat: base}\n"
        "    alternate: {chat: base}\n",
        encoding="utf-8",
    )
    path.with_name("config.local.yaml").write_text(
        "model_presets:\n  active_routing: default\n", encoding="utf-8"
    )
    monkeypatch.setattr(settings_llm, "CONFIG_FILE", path)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            settings_llm.set_active_routing(
                settings_llm.ActiveRoutingUpdate(active_routing="alternate")
            )
        )

    assert exc.value.status_code == 409
    assert _read(path)["model_presets"]["active_routing"] == "default"
