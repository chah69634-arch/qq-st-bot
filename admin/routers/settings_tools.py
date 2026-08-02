"""Admin control plane for registered tool exposure presets.

It controls built-in registered tools and the schemas that reach a particular
chat model preset.  MCP remains an independent subsystem.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from admin.auth import require_scopes
from admin.config_control import read_config_file, write_config_file
from core.config_loader import get_config
from core.tool_presets import normalize_tool_presets

router = APIRouter()
CONFIG_FILE = Path("config.yaml")
_MAX_PRESETS = 32
_MAX_TOOLS_PER_PRESET = 64


class ToolPresetInput(BaseModel):
    name: str
    tools: list[str] = Field(default_factory=list)


class ToolControlUpdate(BaseModel):
    tool_presets: Optional[list[ToolPresetInput]] = None
    model_bindings: Optional[dict[str, Optional[str]]] = None
    execution_enabled: Optional[dict[str, bool]] = None


def _static_tool_enabled(name: str, tools_config: dict) -> bool:
    value = tools_config.get(name)
    if isinstance(value, dict):
        return bool(value.get("enabled", True))
    if value is not None:
        return bool(value)
    return True


def _registry_rows(cfg: dict) -> list[dict]:
    from core.tool_dispatcher import _TOOL_REGISTRY

    tools_config = cfg.get("tools", {})
    rows: list[dict] = []
    for name, info in _TOOL_REGISTRY.items():
        # Dynamic MCP registration is necessarily incomplete while servers are
        # offline.  Do not present that transient subset as a tool catalogue.
        if info.get("category") == "mcp":
            continue
        rows.append({
            "name": name,
            "description": (info.get("description") or info.get("desc") or "").strip(),
            "category": info.get("category") or "other",
            "execution_enabled": _static_tool_enabled(name, tools_config),
        })
    return sorted(rows, key=lambda item: (item["category"], item["name"]))


def _response(cfg: dict) -> dict:
    tool_loop = cfg.get("tool_loop", {})
    model_presets = cfg.get("model_presets", {}).get("presets", {})
    builtin_names = {row["name"] for row in _registry_rows(cfg)}
    tool_presets = [
        {"name": item["name"], "tools": [tool for tool in item["tools"] if tool in builtin_names]}
        for item in normalize_tool_presets(tool_loop.get("tool_presets"))
    ]
    return {
        "tools": _registry_rows(cfg),
        "tool_presets": tool_presets,
        "model_bindings": {
            name: preset.get("tool_preset")
            for name, preset in model_presets.items()
            if isinstance(preset, dict) and preset.get("tool_preset")
        },
        "model_presets": sorted(model_presets),
        "legacy_mode": "model_presets" not in cfg,
        "mcp_enabled": bool(cfg.get("mcp_servers", {}).get("enabled", False)),
    }


@router.get("/settings/tools", summary="Read registered tools and model-specific exposure presets")
async def get_tool_controls(auth=Depends(require_scopes("admin"))):
    return _response(get_config())


def _validate_presets(raw: list[ToolPresetInput], registry_names: set[str]) -> list[dict]:
    if len(raw) > _MAX_PRESETS:
        raise HTTPException(status_code=422, detail=f"最多保存 {_MAX_PRESETS} 个工具预设")
    result: list[dict] = []
    names: set[str] = set()
    for preset in raw:
        name = preset.name.strip()
        if not name or len(name) > 64:
            raise HTTPException(status_code=422, detail="工具预设名称需为 1-64 个字符")
        if name in names:
            raise HTTPException(status_code=422, detail=f"工具预设名称重复: {name}")
        if len(preset.tools) > _MAX_TOOLS_PER_PRESET:
            raise HTTPException(status_code=422, detail=f"预设 {name} 最多包含 {_MAX_TOOLS_PER_PRESET} 个工具")
        tools = list(dict.fromkeys(tool.strip() for tool in preset.tools if tool.strip()))
        unknown = [tool for tool in tools if tool not in registry_names]
        if unknown:
            raise HTTPException(status_code=422, detail=f"预设 {name} 含未注册工具: {', '.join(unknown)}")
        names.add(name)
        result.append({"name": name, "tools": tools})
    return result


@router.put("/settings/tools", summary="Update tool exposure presets and execution switches")
async def update_tool_controls(body: ToolControlUpdate, auth=Depends(require_scopes("admin"))):
    full_cfg = read_config_file(CONFIG_FILE)
    cfg_for_validation = get_config()
    rows = _registry_rows(cfg_for_validation)
    registry_names = {row["name"] for row in rows}
    builtin_names = {row["name"] for row in rows}

    tool_loop = full_cfg.setdefault("tool_loop", {})
    if body.tool_presets is not None:
        saved_presets = _validate_presets(body.tool_presets, registry_names)
        tool_loop["tool_presets"] = saved_presets
        # Deleting a preset must not leave a dangling model binding that would
        # silently fail closed on the next chat turn.
        configured_models = full_cfg.get("model_presets", {}).get("presets", {})
        if isinstance(configured_models, dict):
            valid_names = {item["name"] for item in saved_presets}
            for preset in configured_models.values():
                if isinstance(preset, dict) and preset.get("tool_preset") not in valid_names:
                    preset.pop("tool_preset", None)
    else:
        saved_presets = normalize_tool_presets(tool_loop.get("tool_presets"))
    preset_names = {item["name"] for item in saved_presets}

    model_presets = full_cfg.get("model_presets", {}).get("presets")
    if body.model_bindings is not None:
        if not isinstance(model_presets, dict):
            raise HTTPException(status_code=409, detail="当前为 legacy llm 配置；请先初始化 model_presets")
        for model_name, tool_preset in body.model_bindings.items():
            if model_name not in model_presets:
                raise HTTPException(status_code=422, detail=f"未知模型 preset: {model_name}")
            if tool_preset is not None and tool_preset not in preset_names:
                raise HTTPException(status_code=422, detail=f"未知工具预设: {tool_preset}")
            if tool_preset:
                model_presets[model_name]["tool_preset"] = tool_preset
            else:
                model_presets[model_name].pop("tool_preset", None)

    if body.execution_enabled is not None:
        unknown = set(body.execution_enabled) - builtin_names
        if unknown:
            raise HTTPException(status_code=422, detail=f"仅内置工具可设置执行开关: {', '.join(sorted(unknown))}")
        tools_config = full_cfg.setdefault("tools", {})
        for name, enabled in body.execution_enabled.items():
            current = tools_config.get(name)
            if isinstance(current, dict):
                current["enabled"] = enabled
            else:
                tools_config[name] = {"enabled": enabled}

    write_config_file(CONFIG_FILE, full_cfg)
    from core import config_loader
    config_loader.reload_config()
    return _response(get_config())
