"""Effective capability overlay. Absence of state preserves legacy behavior."""
from __future__ import annotations

from typing import Any

from core.self_management import registry, store


def _grant(state: dict[str, Any], capability_id: str) -> dict[str, Any] | None:
    value = (state.get("grants") or {}).get(capability_id)
    return value if isinstance(value, dict) else None


def _selected(state: dict[str, Any], capability_id: str, default: bool | int) -> bool | int:
    value = (state.get("agent_state") or {}).get(capability_id)
    return value if isinstance(value, (bool, int)) and not isinstance(value, str) else default


def global_available(capability_id: str) -> bool:
    spec = registry.resolve(capability_id)
    if spec is None:
        return False
    if spec.kind == "tool":
        from core.tool_dispatcher import _is_tool_enabled
        return bool(_is_tool_enabled(spec.tool_name))
    return True


def effective(capability_id: str, uid: str, char_id: str) -> tuple[bool, bool | int | None]:
    """Return global availability intersected with user grant and agent choice."""
    if not global_available(capability_id):
        return False, None
    if not store.exists(uid, char_id):
        return True, None
    state = store.load(uid, char_id)
    grant = _grant(state, capability_id)
    # A state file with no record for this capability is still legacy-compatible.
    if grant is None:
        return True, None
    if not bool(grant.get("allowed", False)):
        return False, None
    spec = registry.resolve(capability_id)
    if spec is not None and spec.kind == "autonomy_min_interval":
        value = (state.get("agent_state") or {}).get(capability_id)
        return True, value if isinstance(value, int) and not isinstance(value, bool) else None
    return bool(_selected(state, capability_id, True)), _selected(state, capability_id, True)


def tool_allowed(uid: str, char_id: str, tool_name: str) -> bool:
    capability_id = registry.capability_for_tool(tool_name)
    return capability_id is not None and effective(capability_id, uid, char_id)[0]


def autonomy_enabled(uid: str, char_id: str, base_enabled: bool) -> bool:
    allowed, selected = effective(registry.AUTONOMY_ENABLED, uid, char_id)
    return bool(base_enabled and allowed and (selected is not False))


def autonomy_min_interval(uid: str, char_id: str, base_seconds: int) -> int:
    allowed, value = effective(registry.AUTONOMY_MIN_INTERVAL, uid, char_id)
    if not allowed or not isinstance(value, int) or isinstance(value, bool):
        return int(base_seconds)
    return max(60, int(value))


def can_agent_manage(uid: str, char_id: str, capability_id: str) -> tuple[bool, str]:
    state = store.load(uid, char_id)
    grant = _grant(state, capability_id)
    if registry.resolve(capability_id) is None:
        return False, "unknown_capability"
    if grant is None or not bool(grant.get("allowed", False)):
        return False, "not_granted"
    if not bool(grant.get("mutable_by_agent", False)):
        return False, "managed_by_user_only"
    if bool((state.get("locks") or {}).get(capability_id, False)):
        return False, "locked_by_user"
    if not global_available(capability_id):
        return False, "globally_unavailable"
    return True, "allowed"
