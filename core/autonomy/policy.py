from __future__ import annotations

from core.autonomy.models import Disposition

# Autonomous writes are deliberately narrower than the normal tool-loop
# surface. New entries require an explicit review here; a configurable
# allowlist must never turn a reminder, memory edit, desktop action, or device
# control into an unattended side effect.
_SANDBOXED_WRITE_TOOLS = frozenset({"water_garden"})


def tool_is_eligible(name: str, policy: dict, *, registry: dict, effect: str) -> bool:
    """Return whether one explicitly configured tool is safe for autonomy."""
    info = registry.get(name, {})
    if effect == "read":
        # MCP reads additionally require the operator to acknowledge that an
        # interrupted request has an unknown outcome. Builtins have no remote
        # side effect to reconcile.
        return info.get("category") != "mcp" or (
            bool(policy.get("mcp_explicit"))
            and policy.get("outcome_unknown") == "fail_closed"
        )
    if effect == "write":
        return name in _SANDBOXED_WRITE_TOOLS and info.get("category") == "info"
    return False


def tool_eligibility(name: str, policy: dict, *, registry: dict, effect: str) -> tuple[bool, str]:
    """Public-facing reason used by the configuration API/UI."""
    info = registry.get(name, {})
    if info.get("dangerous") or info.get("require_confirm") or effect not in {"read", "write"}:
        return False, "side_effect_or_confirmation_required"
    if effect == "write" and name not in _SANDBOXED_WRITE_TOOLS:
        return False, "write_not_sandboxed_for_autonomy"
    if info.get("category") == "mcp" and not bool(policy.get("mcp_explicit")):
        return False, "mcp_requires_explicit_enablement"
    if info.get("category") == "mcp" and policy.get("outcome_unknown") != "fail_closed":
        return False, "mcp_requires_fail_closed_outcome_policy"
    return (tool_is_eligible(name, policy, registry=registry, effect=effect), "eligible")


def admission(uid: str, char_id: str, state: dict) -> str | None:
    cfg = state["config"]
    if not cfg.get("enabled", False):
        return Disposition.SUPPRESSED_PROACTIVE_OFF.value
    from core.autonomy.store import circuit_open
    if circuit_open(state):
        return Disposition.CIRCUIT_OPEN.value
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
    # A queued owner message and a held conversation lock are different phases
    # of the normal turn.  Do not start an autonomy run in the gap between them.
    try:
        from core.message_queue import active_sessions, queue_size
        if str(uid) in active_sessions() or queue_size(str(uid)) > 0:
            return Disposition.BLOCKED_USER_ACTIVE.value
    except Exception:
        # Queue observation is advisory; the stronger conversation lock above
        # remains the hard boundary if an optional implementation is unavailable.
        pass
    # Activity sessions own their own user-facing lifecycle. Autonomy must not
    # interleave tools into an active game/reading session.
    try:
        from core.activity.store import find_active_session
        from core.activity.types import ALLOWED_ACTIVITY_TYPES
        if any(find_active_session(char_id, str(uid), kind) for kind in ALLOWED_ACTIVITY_TYPES):
            return Disposition.BLOCKED_USER_ACTIVE.value
        from core.coplay.session import is_active as coplay_active
        if coplay_active(uid, char_id=char_id):
            return Disposition.BLOCKED_USER_ACTIVE.value
    except Exception:
        return Disposition.BLOCKED_USER_ACTIVE.value
    from core.autonomy.store import roll_daily
    roll_daily(state)
    daily = state.get("daily", {})
    if int(daily.get("evaluations") or 0) >= int(cfg.get("daily_evaluation_budget") or 0):
        return Disposition.SUPPRESSED_DAILY_BUDGET.value
    latest = max(
        (float((value or {}).get("last_evaluated_at") or 0) for value in state.get("sources", {}).values()),
        default=0.0,
    )
    import time
    if latest and time.time() - latest < int(cfg.get("min_interval_seconds") or 0):
        return Disposition.DUPLICATE.value
    return None


def allowed_tools(char_id: str, state: dict) -> list[dict]:
    from core.tool_dispatcher import _TOOL_REGISTRY, get_tool_effect, get_tools_schema, is_side_effect_tool
    enabled = state["config"].get("tools", {})
    schemas = {((s.get("function") or s).get("name")): s for s in get_tools_schema(char_id=char_id)}
    out = []
    for name, policy in enabled.items():
        if not isinstance(policy, dict) or not policy.get("enabled") or name not in _TOOL_REGISTRY or name not in schemas:
            continue
        info = _TOOL_REGISTRY[name]
        effect = get_tool_effect(name) or ("write" if is_side_effect_tool(name) else "read")
        eligible, _ = tool_eligibility(name, policy, registry=_TOOL_REGISTRY, effect=effect)
        if not eligible:
            continue
        out.append(schemas[name])
    return out
