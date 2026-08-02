from __future__ import annotations

from core.autonomy.models import Disposition


def admission(uid: str, char_id: str, state: dict) -> str | None:
    cfg = state["config"]
    if not cfg.get("enabled", False):
        return Disposition.SUPPRESSED_PROACTIVE_OFF.value
    from core.character_loader import is_proactive_disabled
    if is_proactive_disabled():
        return Disposition.SUPPRESSED_PROACTIVE_OFF.value
    from core.dream.dream_state import DreamGuardStatus, get_reality_guard_status
    try:
        guard = get_reality_guard_status(uid)
    except Exception:
        return Disposition.BLOCKED_DREAM_UNCERTAIN.value
    if guard == DreamGuardStatus.BLOCK_UNCERTAIN:
        return Disposition.BLOCKED_DREAM_UNCERTAIN.value
    if guard != DreamGuardStatus.ALLOW:
        return Disposition.BLOCKED_DREAM.value
    from core.scheduler.state_machine import TriggerState, get_state
    if get_state(uid) != TriggerState.QUIET:
        return Disposition.BLOCKED_USER_ACTIVE.value
    from core.conversation_gate import conversation_lock
    if conversation_lock(uid).locked():
        return Disposition.BLOCKED_USER_ACTIVE.value
    daily = state.get("daily", {})
    if int(daily.get("evaluations") or 0) >= int(cfg.get("daily_evaluation_budget") or 0):
        return Disposition.SUPPRESSED_DAILY_BUDGET.value
    return None


def allowed_tools(char_id: str, state: dict) -> list[dict]:
    from core.tool_dispatcher import _TOOL_REGISTRY, get_tool_effect, get_tools_schema
    enabled = state["config"].get("tools", {})
    schemas = {((s.get("function") or s).get("name")): s for s in get_tools_schema(char_id=char_id)}
    out = []
    for name, policy in enabled.items():
        if not isinstance(policy, dict) or not policy.get("enabled") or name not in _TOOL_REGISTRY or name not in schemas:
            continue
        info = _TOOL_REGISTRY[name]
        effect = get_tool_effect(name) or ("write" if info.get("dangerous") else "read")
        if effect not in {"read", "write"} or info.get("dangerous") or info.get("require_confirm"):
            continue
        if info.get("category") == "mcp" and not policy.get("mcp_explicit", False):
            continue
        out.append(schemas[name])
    return out
