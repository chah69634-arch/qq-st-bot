"""Typed, allowlisted setting mutations for the Self Capability gateway."""
from __future__ import annotations

import asyncio
from copy import deepcopy
from pathlib import Path
from typing import Any

from admin.config_control import read_config_file, write_config_file
from core import config_loader


def get_config() -> dict:
    return config_loader.get_config()


def reload_config() -> dict:
    return config_loader.reload_config()

CONFIG_FILE = Path("config.yaml")
_MISSING = object()


def _path_get(root: dict, path: tuple[str, ...], default: Any = None) -> Any:
    current: Any = root
    for part in path:
        if not isinstance(current, dict) or part not in current:
            return default
        current = current[part]
    return deepcopy(current)


def _path_set(root: dict, path: tuple[str, ...], value: Any) -> None:
    current = root
    for part in path[:-1]:
        child = current.get(part)
        if not isinstance(child, dict):
            child = {}
            current[part] = child
        current = child
    current[path[-1]] = deepcopy(value)


def _server(name: str, cfg: dict | None = None) -> dict | None:
    config = cfg if cfg is not None else get_config()
    for item in ((config.get("mcp_servers") or {}).get("servers") or []):
        if isinstance(item, dict) and str(item.get("name") or "") == name:
            return item
    return None


def _tool_names() -> set[str]:
    from core.tool_dispatcher import _TOOL_REGISTRY
    return set(_TOOL_REGISTRY)


def _validate_value(capability_id: str, value: Any, spec) -> tuple[bool, str]:
    kind = spec.value_type
    if kind == "bool" and not isinstance(value, bool):
        return False, "invalid_value_type"
    if kind == "integer" and (isinstance(value, bool) or not isinstance(value, int)):
        return False, "invalid_value_type"
    if kind == "number" and (isinstance(value, bool) or not isinstance(value, (int, float))):
        return False, "invalid_value_type"
    if kind == "string_list" and (not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value)):
        return False, "invalid_value_type"
    if kind == "object" and not isinstance(value, dict):
        return False, "invalid_value_type"
    value = deepcopy(value)
    cid = capability_id
    if cid.endswith(".max_steps") or cid.endswith(".max_tools"):
        if not 1 <= value <= 8:
            return False, "out_of_range"
    if cid.endswith(".max_write_tools") and not 0 <= value <= 8:
        return False, "out_of_range"
    if cid.endswith(".total_timeout_s") or cid.endswith(".total_timeout_seconds"):
        if not 1 <= value <= 720:
            return False, "out_of_range"
    if cid.endswith(".tool_timeout_seconds") and not 1 <= value <= 120:
        return False, "out_of_range"
    if cid.endswith(".presence_nag_minutes") and value <= 0:
        return False, "out_of_range"
    if cid.endswith(".global_proactive_min_gap_seconds") and not 1 <= value <= 86400:
        return False, "out_of_range"
    if cid.endswith(".global_proactive_min_gap_hours") and not 0 < float(value) <= 24:
        return False, "out_of_range"
    if cid.endswith(".min_interval_seconds") and not 60 <= value <= 86400:
        return False, "out_of_range"
    if cid.endswith(".interval.seconds") and not 60 <= value <= 31 * 86400:
        return False, "out_of_range"
    if cid.endswith(".daily_evaluation_budget") and not 1 <= value <= 100:
        return False, "out_of_range"
    if cid.endswith("exposure:path_a") or cid.endswith("exposure:path_c"):
        unknown = set(value) - {"categories", "tools", "exclude_tools"}
        if unknown:
            return False, "unknown_setting_field"
        for field in ("categories", "tools", "exclude_tools"):
            if field in value and (not isinstance(value[field], list) or any(not isinstance(item, str) for item in value[field])):
                return False, "invalid_value_type"
        for field in ("tools", "exclude_tools"):
            if field in value and set(value[field]) - _tool_names():
                return False, "unknown_tool"
    if cid.startswith("setting.tool_loop.preset:"):
        unknown = set(value) - _tool_names()
        if unknown:
            return False, "unknown_tool"
    if cid.startswith("setting.tool_loop.") and cid.endswith((".categories", ".exclude_tools")):
        if any(not isinstance(item, str) for item in value):
            return False, "invalid_value_type"
        if cid.endswith(".exclude_tools") and set(value) - _tool_names():
            return False, "unknown_tool"
    if cid.startswith("setting.mcp.server:") and cid.endswith(".allowlist"):
        rest = cid[len("setting.mcp.server:"):-len(".allowlist")]
        server = _server(rest)
        if server is None:
            return False, "unknown_mcp_server"
        known = set(str(item) for item in (server.get("allow_tools") or []))
        try:
            from core.mcp_client import server_runtime
            from core.tool_dispatcher import _TOOL_REGISTRY
            for registered in server_runtime(rest).get("registered_tools") or []:
                info = _TOOL_REGISTRY.get(str(registered)) or {}
                if info.get("mcp_server") == rest and info.get("mcp_tool"):
                    known.add(str(info["mcp_tool"]))
        except Exception:
            pass
        if (not known and value) or (known and not set(value).issubset(known)):
            return False, "unknown_mcp_tool"
    if cid.startswith("setting.mcp.server:") and ".policy:" in cid:
        if not isinstance(value, dict) or set(value) - {"effect", "require_confirm", "idempotent"}:
            return False, "unknown_setting_field"
        if "effect" in value and value["effect"] not in {"read", "write", "actuate", "emergency", "unrestricted"}:
            return False, "invalid_policy_effect"
        if "require_confirm" in value and not isinstance(value["require_confirm"], bool):
            return False, "invalid_value_type"
        if "idempotent" in value and not isinstance(value["idempotent"], bool):
            return False, "invalid_value_type"
        effect = str(value.get("effect") or "")
        if effect in {"actuate", "emergency", "unrestricted"}:
            return False, "high_risk_requires_admin"
    return True, "allowed"


def read(uid: str, char_id: str, capability_id: str) -> Any:
    """Read one safe setting without returning transport or secret material."""
    cid = str(capability_id)
    if cid.startswith("setting.autonomy."):
        from core.autonomy import store
        cfg = store.load(uid, char_id).get("config") or {}
        field = cid[len("setting.autonomy."):].split(".")
        return _path_get(cfg, tuple(field))
    cfg = get_config()
    if cid.startswith("setting.tool_loop.preset:"):
        name = cid.split(":", 1)[1]
        for item in (cfg.get("tool_loop") or {}).get("tool_presets") or []:
            if isinstance(item, dict) and str(item.get("name") or "") == name:
                return list(item.get("tools") or [])
        return []
    if cid.startswith("setting.tool_loop.exposure:"):
        path = cid.split(":", 1)[1]
        return deepcopy(((cfg.get("tool_exposure") or {}).get(path) or {}))
    if cid.startswith("setting.tool_loop."):
        return _path_get(cfg, ("tool_loop", cid[len("setting.tool_loop."):]))
    if cid.startswith("setting.tool.") and cid.endswith(".enabled"):
        name = cid[len("setting.tool."):-len(".enabled")]
        value = (cfg.get("tools") or {}).get(name)
        return bool(value.get("enabled", True)) if isinstance(value, dict) else bool(value if value is not None else True)
    if cid.startswith("setting.mcp.server:"):
        rest = cid[len("setting.mcp.server:"):]
        name, _, field = rest.rpartition(".")
        server = _server(name, cfg)
        if field.startswith("policy:"):
            tool_name = field.split(":", 1)[1]
            policy = deepcopy(((server or {}).get("tool_policy") or {}).get(tool_name) or {})
            return {key: policy.get(key) for key in ("effect", "require_confirm", "idempotent") if key in policy}
        return deepcopy((server or {}).get(field))
    if cid.startswith("setting.mcp."):
        return _path_get(cfg, ("mcp_servers", cid[len("setting.mcp."):]))
    if cid.startswith("setting.scheduler."):
        return _path_get(cfg, ("scheduler", cid[len("setting.scheduler."):]))
    return None


def _write_global(cid: str, value: Any) -> tuple[Any, Any]:
    document = read_config_file(CONFIG_FILE)
    old = read("", "", cid)
    if cid.startswith("setting.tool_loop.preset:"):
        name = cid.split(":", 1)[1]
        loop = document.setdefault("tool_loop", {})
        presets = loop.setdefault("tool_presets", [])
        found = False
        for item in presets:
            if isinstance(item, dict) and str(item.get("name") or "") == name:
                item["tools"] = list(value); found = True; break
        if not found:
            presets.append({"name": name, "tools": list(value)})
    elif cid.startswith("setting.tool_loop.exposure:"):
        path = cid.split(":", 1)[1]
        document.setdefault("tool_exposure", {})[path] = deepcopy(value)
    elif cid.startswith("setting.tool_loop."):
        _path_set(document, ("tool_loop", cid[len("setting.tool_loop."):]), value)
    elif cid.startswith("setting.tool.") and cid.endswith(".enabled"):
        name = cid[len("setting.tool."):-len(".enabled")]
        document.setdefault("tools", {}).setdefault(name, {})["enabled"] = value
    elif cid.startswith("setting.mcp.server:"):
        rest = cid[len("setting.mcp.server:"):]
        name, _, field = rest.rpartition(".")
        servers = (document.setdefault("mcp_servers", {})).setdefault("servers", [])
        server = next((item for item in servers if isinstance(item, dict) and str(item.get("name") or "") == name), None)
        if server is None:
            return old, _MISSING
        if field.startswith("policy:"):
            tool_name = field.split(":", 1)[1]
            policies = server.setdefault("tool_policy", {})
            current = policies.setdefault(tool_name, {})
            current.update(deepcopy(value))
        else:
            server[field if field else "enabled"] = deepcopy(value)
    elif cid.startswith("setting.mcp."):
        _path_set(document, ("mcp_servers", cid[len("setting.mcp."):]), value)
    elif cid.startswith("setting.scheduler."):
        _path_set(document, ("scheduler", cid[len("setting.scheduler."):]), value)
    else:
        return old, _MISSING
    write_config_file(CONFIG_FILE, document)
    reload_config()
    return old, read("", "", cid)


def write(uid: str, char_id: str, capability_id: str, value: Any) -> tuple[Any, Any, str]:
    """Apply one allowlisted setting and return old/new values plus a reason code."""
    from core.self_management import registry
    spec = registry.resolve(capability_id)
    if spec is None or spec.kind != "setting":
        return None, None, "unknown_capability"
    valid, code = _validate_value(registry._canonical(capability_id), value, spec)
    if not valid:
        return None, None, code
    cid = registry._canonical(capability_id)
    if spec.high_risk:
        return None, None, "high_risk_requires_admin"
    if cid.startswith("setting.autonomy."):
        from core.autonomy import store
        state = store.load(uid, char_id)
        cfg = deepcopy(state.get("config") or {})
        old = _path_get(cfg, tuple(cid[len("setting.autonomy."):].split(".")))
        _path_set(cfg, tuple(cid[len("setting.autonomy."):].split(".")), value)
        if not store.replace_config(uid, char_id, cfg):
            return old, old, "persistence_failed"
        registry.rebuild_effective_schema()
        return old, value, "applied"
    try:
        old, new = _write_global(cid, value)
    except Exception:
        return None, None, "persistence_failed"
    if new is _MISSING:
        return old, old, "unknown_setting"
    # MCP ownership is task-local; signal the owner task instead of touching a
    # session from this synchronous request path.
    if cid.startswith("setting.mcp"):
        try:
            from core.mcp_client import reload_server_from_config, sync_mcp_servers
            loop = asyncio.get_running_loop()
            if cid.startswith("setting.mcp.server:"):
                name = cid[len("setting.mcp.server:"):].rsplit(".", 1)[0]
                loop.create_task(reload_server_from_config(name))
            else:
                loop.create_task(sync_mcp_servers())
        except Exception:
            pass
    registry.rebuild_effective_schema()
    return old, new, "applied"


def restore(uid: str, char_id: str, capability_id: str, value: Any) -> tuple[bool, str]:
    """Restore the captured baseline value for an agent mutation."""
    _, _, code = write(uid, char_id, capability_id, value)
    return code == "applied", code
