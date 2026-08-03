"""Closed capability registry. It accepts names only when a live tool backs them."""
from __future__ import annotations

from dataclasses import dataclass

AUTONOMY_ENABLED = "autonomy.enabled"
AUTONOMY_MIN_INTERVAL = "autonomy.min_interval_seconds"


@dataclass(frozen=True)
class CapabilitySpec:
    capability_id: str
    kind: str
    tool_name: str = ""


def capability_for_tool(tool_name: str) -> str | None:
    from core.tool_dispatcher import _TOOL_REGISTRY

    info = _TOOL_REGISTRY.get(tool_name)
    if not isinstance(info, dict):
        return None
    if info.get("self_management"):
        # The management gateway is intentionally never a managed capability.
        return None
    if info.get("category") == "mcp":
        server = str(info.get("mcp_server") or "")
        tool = str(info.get("mcp_tool") or "")
        if not server or not tool:
            return None
        return f"mcp.use:{server}/{tool}"
    return f"tool.use:{tool_name}"


def resolve(capability_id: str) -> CapabilitySpec | None:
    if capability_id == AUTONOMY_ENABLED:
        return CapabilitySpec(capability_id, "autonomy_enabled")
    if capability_id == AUTONOMY_MIN_INTERVAL:
        return CapabilitySpec(capability_id, "autonomy_min_interval")
    if capability_id.startswith("tool.use:"):
        tool_name = capability_id[len("tool.use:"):]
        if capability_for_tool(tool_name) == capability_id:
            return CapabilitySpec(capability_id, "tool", tool_name)
    if capability_id.startswith("mcp.use:"):
        from core.tool_dispatcher import _TOOL_REGISTRY
        suffix = capability_id[len("mcp.use:"):]
        for name, info in _TOOL_REGISTRY.items():
            if info.get("category") != "mcp":
                continue
            if f"{info.get('mcp_server')}/{info.get('mcp_tool')}" == suffix:
                return CapabilitySpec(capability_id, "tool", name)
    return None


def display_name(capability_id: str) -> str:
    spec = resolve(capability_id)
    return spec.tool_name if spec and spec.kind == "tool" else capability_id


def list_available() -> list[CapabilitySpec]:
    """Return capability IDs only; never expose transport configuration."""
    from core.tool_dispatcher import _TOOL_REGISTRY

    items = [
        CapabilitySpec(AUTONOMY_ENABLED, "autonomy_enabled"),
        CapabilitySpec(AUTONOMY_MIN_INTERVAL, "autonomy_min_interval"),
    ]
    for tool_name in _TOOL_REGISTRY:
        capability_id = capability_for_tool(tool_name)
        if capability_id:
            spec = resolve(capability_id)
            if spec is not None:
                items.append(spec)
    return sorted({item.capability_id: item for item in items}.values(), key=lambda item: item.capability_id)
