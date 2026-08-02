"""Named tool exposure presets for the agentic tool loop.

The registry and ``tools.<name>.enabled`` remain the execution authority.  This
module only narrows the schemas sent to a model for one chat model preset.
Keeping the two concerns separate means a relay with a small tool-schema budget
does not accidentally disable a tool for every other route.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def normalize_tool_presets(value: Any) -> list[dict[str, list[str] | str]]:
    """Return well-formed named presets, ignoring malformed legacy entries."""
    if not isinstance(value, list):
        return []
    result: list[dict[str, list[str] | str]] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name or name in seen:
            continue
        tools = item.get("tools")
        if not isinstance(tools, list):
            continue
        seen.add(name)
        result.append({"name": name, "tools": [str(tool) for tool in tools if str(tool)]})
    return result


def resolve_tool_allowlist(tool_loop: dict | None, model_preset: dict | None) -> tuple[set[str] | None, str | None]:
    """Resolve the optional named allowlist for one model preset.

    ``None`` preserves the historical category-based exposure.  A configured
    but missing named preset resolves to an empty set (fail closed): it is safer
    than unexpectedly restoring every tool after an admin deletes a preset.
    """
    configured_name = (model_preset or {}).get("tool_preset")
    if not isinstance(configured_name, str) or not configured_name.strip():
        return None, None
    configured_name = configured_name.strip()
    for preset in normalize_tool_presets((tool_loop or {}).get("tool_presets")):
        if preset["name"] == configured_name:
            return set(preset["tools"]), configured_name
    logger.warning("[tool_presets] missing tool preset binding=%r; exposing no tools", configured_name)
    return set(), configured_name
