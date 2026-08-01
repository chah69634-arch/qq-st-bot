"""MCP 外部工具的管理面配置、连接测试与热重载（Brief 110）。"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Literal, Optional
from urllib.parse import urlparse

import yaml
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from admin.auth import require_scopes
from core.config_loader import get_config

router = APIRouter()
CONFIG_FILE = Path("config.yaml")
_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")
_REMOTE_TRANSPORTS = ("sse", "streamable-http")


class McpServerDraft(BaseModel):
    name: str
    url: str
    transport: Literal["sse", "streamable-http", "http"] = "streamable-http"
    use_proxy: bool = False
    headers: dict[str, str] = Field(default_factory=dict)
    allow_tools: list[str] = Field(default_factory=list)
    tool_policy: Optional[dict[str, "McpToolPolicy"]] = None
    enabled: bool = True
    tool_timeout_s: float = 30
    tool_timeouts_s: dict[str, float] = Field(default_factory=dict)


class McpSettingsUpdate(BaseModel):
    enabled: Optional[bool] = None


class McpToolPolicy(BaseModel):
    effect: Literal["read", "write", "actuate", "emergency"]
    require_confirm: Optional[bool] = None
    idempotent: Optional[bool] = None


class McpServerUpdate(BaseModel):
    enabled: Optional[bool] = None
    allow_tools: Optional[list[str]] = None
    tool_policy: Optional[dict[str, McpToolPolicy]] = None
    headers: Optional[dict[str, str]] = None
    tool_timeout_s: Optional[float] = None
    tool_timeouts_s: Optional[dict[str, float]] = None
    use_proxy: Optional[bool] = None
    tool_presets: Optional[list[dict]] = None
    active_tool_preset: Optional[str] = None


def _validate_draft(draft: McpServerDraft) -> dict:
    name = draft.name.strip()
    if not _NAME_RE.fullmatch(name):
        raise HTTPException(status_code=422, detail="name 只能含字母、数字、_、-，且必须以字母开头")
    parsed = urlparse(draft.url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(status_code=422, detail="URL 必须是完整的 http(s) MCP endpoint")
    if draft.transport not in {*_REMOTE_TRANSPORTS, "http"}:
        raise HTTPException(
            status_code=422,
            detail="transport 仅支持 sse 或 streamable-http（http 仅为兼容别名）",
        )
    if not all(key.strip() and value for key, value in draft.headers.items()):
        raise HTTPException(status_code=422, detail="headers 的键和值都必须是非空字符串")
    if len(draft.allow_tools) > 200:
        raise HTTPException(status_code=422, detail="allow_tools 最多 200 项")
    return {
        "name": name,
        "transport": draft.transport,
        "use_proxy": bool(draft.use_proxy),
        "url": draft.url.strip(),
        "headers": dict(draft.headers),
        "allow_tools": list(dict.fromkeys(draft.allow_tools)),
        **(
            {"tool_policy": {
                tool_name: policy.model_dump(exclude_none=True)
                for tool_name, policy in draft.tool_policy.items()
            }}
            if draft.tool_policy is not None else {}
        ),
        "enabled": bool(draft.enabled),
        "tool_timeout_s": max(1, min(300, float(draft.tool_timeout_s))),
        "tool_timeouts_s": _normalize_tool_timeouts(draft.tool_timeouts_s),
    }


def _normalize_tool_timeouts(raw: object) -> dict[str, float]:
    if not isinstance(raw, dict) or len(raw) > 200:
        raise HTTPException(status_code=422, detail="tool_timeouts_s 必须是不超过 200 项的对象")
    normalized: dict[str, float] = {}
    for tool_name, timeout_s in raw.items():
        if not isinstance(tool_name, str) or not tool_name:
            raise HTTPException(status_code=422, detail="tool_timeouts_s 的工具名必须是非空字符串")
        try:
            value = float(timeout_s)
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail="tool_timeouts_s 的值必须是秒数") from exc
        if not 1 <= value <= 300:
            raise HTTPException(status_code=422, detail="tool_timeouts_s 的值必须在 1-300 秒")
        normalized[tool_name] = value
    return normalized


def _read_config() -> dict:
    try:
        with CONFIG_FILE.open("r", encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"读取配置文件失败: {exc}") from exc


def _write_config(cfg: dict) -> None:
    try:
        with CONFIG_FILE.open("w", encoding="utf-8") as fh:
            yaml.dump(cfg, fh, allow_unicode=True, default_flow_style=False, sort_keys=False)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"写入配置文件失败: {exc}") from exc


def _safe_headers(headers: object) -> dict[str, str]:
    """管理面永不回显字面 token；${ENV_VAR} 可安全显示以便排查绑定关系。"""
    if not isinstance(headers, dict):
        return {}
    return {
        str(key): value if isinstance(value, str) and "${" in value else "••••已配置"
        for key, value in headers.items()
    }


def _normalize_tool_presets(raw: object) -> list[dict[str, object]]:
    """Validate the per-server named allowlist presets stored in config.yaml."""
    if raw is None:
        return []
    if not isinstance(raw, list) or len(raw) > 50:
        raise HTTPException(status_code=422, detail="tool_presets 最多 50 个，且必须是列表")
    normalized: list[dict[str, object]] = []
    names: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            raise HTTPException(status_code=422, detail="每个工具预设必须是对象")
        name = str(item.get("name") or "").strip()
        tools = item.get("tools")
        if not name or len(name) > 64:
            raise HTTPException(status_code=422, detail="工具预设名称不能为空，且最多 64 个字符")
        if name in names:
            raise HTTPException(status_code=422, detail=f"工具预设名称重复: {name}")
        if not isinstance(tools, list) or len(tools) > 200 or not all(isinstance(tool, str) and tool for tool in tools):
            raise HTTPException(status_code=422, detail="工具预设的 tools 必须是最多 200 项的非空字符串列表")
        names.add(name)
        normalized.append({"name": name, "tools": list(dict.fromkeys(tools))})
    return normalized


def _prune_tool_policy(server: dict) -> None:
    """Keep persisted policy entries only for currently allowlisted tools."""
    policy = server.get("tool_policy")
    if not isinstance(policy, dict):
        server.pop("tool_policy", None)
        return
    allowed = set(server.get("allow_tools") or [])
    filtered = {name: value for name, value in policy.items() if name in allowed}
    if filtered:
        server["tool_policy"] = filtered
    else:
        server.pop("tool_policy", None)


def _server_view(server_cfg: dict, *, require_local_policy: bool = False) -> dict:
    from core.mcp_client import is_local_mcp_url, server_runtime, suggest_tool_policy

    name = str(server_cfg.get("name") or "")
    runtime = server_runtime(name)
    allowed = set(server_cfg.get("allow_tools") or [])
    policy = dict(server_cfg.get("tool_policy") or {})
    tool_states: list[dict] = []
    for tool in runtime.get("tools", []):
        tool_name = str(tool.get("name") or "")
        if not tool_name:
            continue
        suggestion = tool.get("suggestion") or suggest_tool_policy(
            tool_name, str(tool.get("description") or ""),
        )
        allowlisted = not allowed or tool_name in allowed
        confirmed = isinstance(policy.get(tool_name), dict)
        if not allowlisted:
            policy_status = "not_allowlisted"
        elif confirmed:
            policy_status = "confirmed"
        elif require_local_policy:
            policy_status = "pending_confirmation"
        else:
            policy_status = "legacy_allowed"
        tool_states.append({
            "name": tool_name,
            "description": str(tool.get("description") or ""),
            "allowlisted": allowlisted,
            "policy_status": policy_status,
            "suggestion": suggestion,
            "policy": policy.get(tool_name),
        })
    return {
        "name": name,
        "transport": server_cfg.get("transport", "stdio"),
        "url": server_cfg.get("url", ""),
        "use_proxy": bool(server_cfg.get("use_proxy", False)),
        "is_local_url": is_local_mcp_url(str(server_cfg.get("url") or "")),
        "headers": _safe_headers(server_cfg.get("headers")),
        "enabled": bool(server_cfg.get("enabled", True)),
        "tool_timeout_s": float(server_cfg.get("tool_timeout_s", 30)),
        "tool_timeouts_s": dict(server_cfg.get("tool_timeouts_s") or {}),
        "allow_tools": list(server_cfg.get("allow_tools") or []),
        "tool_policy": policy,
        "tool_states": tool_states,
        "tool_presets": _normalize_tool_presets(server_cfg.get("tool_presets")),
        "active_tool_preset": str(server_cfg.get("active_tool_preset") or ""),
        "runtime": runtime,
    }


@router.get("/settings/mcp", summary="读取 MCP server 配置与运行状态")
async def get_mcp_settings(_auth=Depends(require_scopes("admin"))):
    cfg = get_config().get("mcp_servers", {}) or {}
    servers = [item for item in (cfg.get("servers") or []) if isinstance(item, dict)]
    return {
        "enabled": bool(cfg.get("enabled", False)),
        "servers": [
            _server_view(item, require_local_policy=bool(cfg.get("require_local_policy", False)))
            for item in servers
        ],
        "warning": "外部 MCP 的工具描述与结果均为不可信输入；不要把密钥写进角色卡、prompt 或文档。",
    }


@router.patch("/settings/mcp", summary="更新 MCP 总开关（写配置并热同步）")
async def update_mcp_settings(body: McpSettingsUpdate, _auth=Depends(require_scopes("admin"))):
    # Brief 115 根治：sync_mcp_servers() 现在只把信号丢进各 server 专属常驻 task 的
    # 队列，真正的 AsyncExitStack.aclose()/重连都在那个专属 task 自己的上下文里执行，
    # 不再从这次 HTTP 请求的 task 里跨 task 直接碰 stack，热同步可以安全恢复。
    if body.enabled is None:
        raise HTTPException(status_code=422, detail="至少提供 enabled")
    full_cfg = _read_config()
    full_cfg.setdefault("mcp_servers", {})["enabled"] = body.enabled
    _write_config(full_cfg)
    from core import config_loader, mcp_client
    config_loader.reload_config()
    await mcp_client.sync_mcp_servers()
    result = await get_mcp_settings(_auth)
    result["message"] = "MCP 总开关已更新并热同步"
    return result


@router.post("/settings/mcp/test", summary="测试 MCP URL 并列出工具（不写配置）")
async def test_mcp_server(body: McpServerDraft, _auth=Depends(require_scopes("admin"))):
    from core.mcp_client import test_server_config

    server_cfg = _validate_draft(body)
    try:
        tools = await test_server_config(server_cfg)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"MCP 连接测试失败: {exc}") from exc
    return {"ok": True, "tools": tools}


@router.post("/settings/mcp/import", summary="测试后导入远程 MCP server")
async def import_mcp_server(body: McpServerDraft, _auth=Depends(require_scopes("admin"))):
    from core import config_loader, mcp_client

    server_cfg = _validate_draft(body)
    full_cfg = _read_config()
    mcp_cfg = full_cfg.setdefault("mcp_servers", {})
    existing = next(
        (
            item
            for item in (mcp_cfg.get("servers") or [])
            if item.get("name") == server_cfg["name"]
        ),
        None,
    )
    # The import form does not edit trusted local tool policy. Retain an
    # existing strict policy when re-importing the same server.
    if isinstance(existing, dict):
        if not server_cfg["allow_tools"] and isinstance(
            existing.get("allow_tools"), list
        ):
            server_cfg["allow_tools"] = list(existing["allow_tools"])
        if isinstance(existing.get("tool_policy"), dict):
            server_cfg["tool_policy"] = dict(existing["tool_policy"])
    if bool(mcp_cfg.get("require_local_policy", False)):
        try:
            mcp_client.validate_local_tool_policy(server_cfg, required=True)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    try:
        tools = await mcp_client.test_server_config(server_cfg)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"MCP 连接测试失败，未写入配置: {exc}") from exc
    discovered_names = {item["name"] for item in tools}
    unknown = sorted(set(server_cfg["allow_tools"]) - discovered_names)
    if unknown:
        raise HTTPException(status_code=422, detail=f"allow_tools 含未发现工具: {unknown}")

    _prune_tool_policy(server_cfg)

    servers = [item for item in (mcp_cfg.get("servers") or []) if item.get("name") != server_cfg["name"]]
    servers.append(server_cfg)
    mcp_cfg["servers"] = servers
    _write_config(full_cfg)
    config_loader.reload_config()
    # Brief 115 根治：热重载已恢复，走 reload_server_from_config 的信号队列，由该
    # server 专属常驻 task 自己 aclose()/重连，不跨 task。测试探测（test_server_config）
    # 用的是独立、当次即开即关的 stack，本来就不受这条根因影响。
    reload_ok = await mcp_client.reload_server_from_config(server_cfg["name"])
    reloaded = reload_ok is not False
    return {
        "message": "MCP server 已导入并连接" if reloaded else "配置已保存，但 MCP 热重载失败，需要重启服务",
        "reload_status": "reloaded" if reloaded else "restart_required",
        "tools": tools,
        "server": _server_view(
            server_cfg, require_local_policy=bool(mcp_cfg.get("require_local_policy", False)),
        ),
    }


@router.patch("/settings/mcp/{name}", summary="更新一个 MCP server 的启停或工具白名单")
async def update_mcp_server(name: str, body: McpServerUpdate, _auth=Depends(require_scopes("admin"))):
    if not _NAME_RE.fullmatch(name):
        raise HTTPException(status_code=422, detail="非法 server name")
    if all(value is None for value in (body.enabled, body.allow_tools, body.tool_policy, body.headers, body.tool_timeout_s, body.tool_timeouts_s, body.use_proxy, body.tool_presets, body.active_tool_preset)):
        raise HTTPException(status_code=422, detail="没有可更新字段")
    full_cfg = _read_config()
    servers = full_cfg.setdefault("mcp_servers", {}).setdefault("servers", [])
    server = next((item for item in servers if item.get("name") == name), None)
    if server is None:
        raise HTTPException(status_code=404, detail="MCP server 不存在")
    if body.enabled is not None:
        server["enabled"] = body.enabled
    if body.allow_tools is not None:
        server["allow_tools"] = list(dict.fromkeys(body.allow_tools))
        # A manual checkbox edit is deliberately a custom selection, not a silent
        # mutation of whichever named preset happened to be active.
        server.pop("active_tool_preset", None)
    if body.tool_policy is not None:
        server["tool_policy"] = {
            tool_name: policy.model_dump(exclude_none=True)
            for tool_name, policy in body.tool_policy.items()
        }
    if body.tool_timeouts_s is not None:
        server["tool_timeouts_s"] = _normalize_tool_timeouts(body.tool_timeouts_s)
    if body.tool_presets is not None:
        server["tool_presets"] = _normalize_tool_presets(body.tool_presets)
        current = str(server.get("active_tool_preset") or "")
        if current and current not in {item["name"] for item in server["tool_presets"]}:
            server.pop("active_tool_preset", None)
    if body.active_tool_preset is not None:
        selected = body.active_tool_preset.strip()
        if not selected:
            server.pop("active_tool_preset", None)
        else:
            presets = _normalize_tool_presets(server.get("tool_presets"))
            preset = next((item for item in presets if item["name"] == selected), None)
            if preset is None:
                raise HTTPException(status_code=422, detail=f"工具预设不存在: {selected}")
            server["active_tool_preset"] = selected
            server["allow_tools"] = list(preset["tools"])
    if body.headers is not None:
        if not all(key.strip() and value for key, value in body.headers.items()):
            raise HTTPException(status_code=422, detail="headers 的键和值都必须是非空字符串")
        server["headers"] = dict(body.headers)
    if body.tool_timeout_s is not None:
        server["tool_timeout_s"] = max(1, min(300, float(body.tool_timeout_s)))
    if body.use_proxy is not None:
        server["use_proxy"] = bool(body.use_proxy)
    _prune_tool_policy(server)
    from core import config_loader, mcp_client
    if (
        bool(full_cfg.get("mcp_servers", {}).get("require_local_policy", False))
        and bool(server.get("enabled", True))
    ):
        try:
            mcp_client.validate_local_tool_policy(server, required=True)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    _write_config(full_cfg)
    config_loader.reload_config()
    # Brief 115 根治：同上，走信号队列热重载，由 server 专属常驻 task 自己关闭/重连。
    reload_ok = await mcp_client.reload_server_from_config(name)
    reloaded = reload_ok is not False
    return {
        "message": "MCP server 配置已更新并热重载" if reloaded else "配置已保存，但 MCP 热重载失败，需要重启服务",
        "reload_status": "reloaded" if reloaded else "restart_required",
        "server": _server_view(
            server,
            require_local_policy=bool(full_cfg.get("mcp_servers", {}).get("require_local_policy", False)),
        ),
    }


@router.delete("/settings/mcp/{name}", summary="删除一个 MCP server 并断开其运行态")
async def delete_mcp_server(name: str, _auth=Depends(require_scopes("admin"))):
    if not _NAME_RE.fullmatch(name):
        raise HTTPException(status_code=422, detail="非法 server name")
    full_cfg = _read_config()
    mcp_cfg = full_cfg.setdefault("mcp_servers", {})
    servers = mcp_cfg.setdefault("servers", [])
    remaining = [item for item in servers if not isinstance(item, dict) or item.get("name") != name]
    if len(remaining) == len(servers):
        raise HTTPException(status_code=404, detail="MCP server 不存在")
    mcp_cfg["servers"] = remaining
    _write_config(full_cfg)

    from core import config_loader, mcp_client

    config_loader.reload_config()
    # sync 会向已被删除的 server owner 发 shutdown，摘除动态工具并关闭连接。
    await mcp_client.sync_mcp_servers()
    return {"message": "MCP server 已删除并断开", "deleted": name}
