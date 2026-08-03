"""Narrow mutation service shared by admin controls and the Agent-only tool."""
from __future__ import annotations

import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from threading import RLock
from typing import Any

from core.self_management import policy, registry, store
from core.self_management.models import CapabilityChange, ChangeResult

_MUTATION_LOCK = RLock()
_AUDIT_CONTEXT: ContextVar[dict[str, str]] = ContextVar("self_management_audit_context", default={})


@contextmanager
def autonomy_audit_context(*, run_id: str, job_id: str):
    """Attach bounded autonomy identifiers to capability audit records."""
    token = _AUDIT_CONTEXT.set({"run_id": str(run_id)[:128], "job_id": str(job_id)[:128]})
    try:
        yield
    finally:
        _AUDIT_CONTEXT.reset(token)


def _reason(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value[:240] if value else None


def _audit(uid: str, char_id: str, *, action_id: str, actor: str, source: str, capability_id: str, old_value, new_value, reason: str, before: int, after: int, result: str, old_effective_value=None, new_effective_value=None) -> None:
    record = {
        "event_id": uuid.uuid4().hex,
        "action_id": action_id[:128],
        "actor": actor,
        "source": source[:64],
        "capability_id": capability_id,
        "old_value": old_value,
        "new_value": new_value,
        "reason": reason[:240],
        "revision_before": before,
        "revision_after": after,
        "result": result,
        "old_effective_value": old_effective_value,
        "new_effective_value": new_effective_value,
    }
    record.update(_AUDIT_CONTEXT.get())
    store.append_audit(uid, char_id, record)


def _constraints_valid(capability_id: str, grant: dict, value: object) -> bool:
    spec = registry.resolve(capability_id)
    if spec is None:
        return False
    if spec.kind == "autonomy_min_interval":
        if isinstance(value, bool) or not isinstance(value, int) or value < 60:
            return False
        constraints = grant.get("constraints") or {}
        try:
            minimum = max(60, int(constraints.get("minimum", 60)))
            maximum = int(constraints.get("maximum", 31 * 86400))
        except (TypeError, ValueError):
            return False
        return minimum <= value <= maximum
    return isinstance(value, bool)


def agent_change(uid: str, char_id: str, change: CapabilityChange, *, source: str) -> ChangeResult:
    if source not in {"assistant_self_management", "autonomy_self_management"}:
        return ChangeResult(False, "invalid_source", store.load(uid, char_id)["revision"])
    if not change.action_id or len(change.action_id) > 128 or not _reason(change.reason):
        state = store.load(uid, char_id); revision = int(state.get("revision") or 0)
        _audit(uid, char_id, action_id=str(change.action_id or uuid.uuid4().hex), actor="agent", source=source, capability_id=str(change.capability_id)[:128], old_value=None, new_value=None, reason=_reason(change.reason) or "invalid request", before=revision, after=revision, result="invalid_request")
        return ChangeResult(False, "invalid_request", revision)
    with _MUTATION_LOCK:
        state = store.load(uid, char_id)
        revision = int(state.get("revision") or 0)
        previous = (state.get("applied_actions") or {}).get(change.action_id)
        if isinstance(previous, dict):
            _audit(uid, char_id, action_id=change.action_id, actor="agent", source=source, capability_id=change.capability_id, old_value=previous.get("value"), new_value=previous.get("value"), reason=change.reason, before=revision, after=revision, result="idempotent")
            return ChangeResult(bool(previous.get("ok")), "idempotent", revision, previous.get("value"))
        if change.expected_revision != revision:
            _audit(uid, char_id, action_id=change.action_id, actor="agent", source=source, capability_id=change.capability_id, old_value=None, new_value=None, reason=change.reason, before=revision, after=revision, result="revision_conflict")
            return ChangeResult(False, "revision_conflict", revision)
        allowed, code = policy.can_agent_manage(uid, char_id, change.capability_id)
        if not allowed:
            _audit(uid, char_id, action_id=change.action_id, actor="agent", source=source, capability_id=change.capability_id, old_value=None, new_value=None, reason=change.reason, before=revision, after=revision, result=code)
            return ChangeResult(False, code, revision)
        grant = state["grants"][change.capability_id]
        spec = registry.resolve(change.capability_id)
        if spec is None:
            _audit(uid, char_id, action_id=change.action_id, actor="agent", source=source, capability_id=change.capability_id, old_value=None, new_value=None, reason=change.reason, before=revision, after=revision, result="unknown_capability")
            return ChangeResult(False, "unknown_capability", revision)
        if change.action == "set_value":
            if spec.kind != "autonomy_min_interval" or not _constraints_valid(change.capability_id, grant, change.value):
                _audit(uid, char_id, action_id=change.action_id, actor="agent", source=source, capability_id=change.capability_id, old_value=state.setdefault("agent_state", {}).get(change.capability_id), new_value=None, reason=change.reason, before=revision, after=revision, result="value_out_of_constraints")
                return ChangeResult(False, "value_out_of_constraints", revision)
            new_value = int(change.value)
        elif change.action in {"enable", "disable"} and spec.kind != "autonomy_min_interval":
            new_value = change.action == "enable"
        else:
            _audit(uid, char_id, action_id=change.action_id, actor="agent", source=source, capability_id=change.capability_id, old_value=state.setdefault("agent_state", {}).get(change.capability_id), new_value=None, reason=change.reason, before=revision, after=revision, result="invalid_action")
            return ChangeResult(False, "invalid_action", revision)
        old_value = state.setdefault("agent_state", {}).get(change.capability_id)
        old_effective_value = policy.effective(change.capability_id, uid, char_id)[1]
        state["agent_state"][change.capability_id] = new_value
        state["revision"] = revision + 1
        state.setdefault("applied_actions", {})[change.action_id] = {"ok": True, "value": new_value, "timestamp": time.time()}
        if not store.save(uid, char_id, state):
            return ChangeResult(False, "persistence_failed", revision)
        new_effective_value = policy.effective(change.capability_id, uid, char_id)[1]
        _audit(uid, char_id, action_id=change.action_id, actor="agent", source=source, capability_id=change.capability_id, old_value=old_value, new_value=new_value, reason=change.reason, before=revision, after=revision + 1, result="applied", old_effective_value=old_effective_value, new_effective_value=new_effective_value)
        return ChangeResult(True, "applied", revision + 1, new_value)


def user_grant(uid: str, char_id: str, *, capability_id: str, allowed: bool, mutable_by_agent: bool, constraints: dict | None, reason: str, source: str = "admin") -> ChangeResult:
    if registry.resolve(capability_id) is None or not isinstance(allowed, bool) or not isinstance(mutable_by_agent, bool) or not _reason(reason):
        return ChangeResult(False, "invalid_request", store.load(uid, char_id)["revision"])
    if constraints is not None and not isinstance(constraints, dict):
        return ChangeResult(False, "invalid_constraints", store.load(uid, char_id)["revision"])
    spec = registry.resolve(capability_id)
    normalized_constraints = {}
    if spec is not None and spec.kind == "autonomy_min_interval":
        raw = constraints or {}
        try:
            minimum = max(60, int(raw.get("minimum", 60)))
            maximum = int(raw.get("maximum", 31 * 86400))
        except (TypeError, ValueError):
            return ChangeResult(False, "invalid_constraints", store.load(uid, char_id)["revision"])
        normalized_constraints = {"minimum": minimum, "maximum": maximum}
        if not _constraints_valid(capability_id, {"constraints": normalized_constraints}, minimum):
            return ChangeResult(False, "invalid_constraints", store.load(uid, char_id)["revision"])
    with _MUTATION_LOCK:
        state = store.load(uid, char_id); before = int(state.get("revision") or 0)
        old_value = (state.get("grants") or {}).get(capability_id)
        grant = {"capability_id": capability_id, "allowed": allowed, "mutable_by_agent": mutable_by_agent, "constraints": normalized_constraints, "granted_by": "user", "granted_at": time.time()}
        state.setdefault("grants", {})[capability_id] = grant
        if not allowed:
            state.setdefault("agent_state", {}).pop(capability_id, None)
        state["revision"] = before + 1
        if not store.save(uid, char_id, state): return ChangeResult(False, "persistence_failed", before)
        _audit(uid, char_id, action_id=uuid.uuid4().hex, actor="user", source=source, capability_id=capability_id, old_value=old_value, new_value=grant, reason=reason, before=before, after=before + 1, result="grant_updated")
        return ChangeResult(True, "grant_updated", before + 1, allowed)


def set_lock(uid: str, char_id: str, *, capability_id: str, locked: bool, reason: str, source: str = "admin") -> ChangeResult:
    if registry.resolve(capability_id) is None or not isinstance(locked, bool) or not _reason(reason): return ChangeResult(False, "invalid_request", store.load(uid, char_id)["revision"])
    with _MUTATION_LOCK:
        state = store.load(uid, char_id); before = int(state.get("revision") or 0); old = bool((state.get("locks") or {}).get(capability_id, False))
        state.setdefault("locks", {})[capability_id] = locked; state["revision"] = before + 1
        if not store.save(uid, char_id, state): return ChangeResult(False, "persistence_failed", before)
        _audit(uid, char_id, action_id=uuid.uuid4().hex, actor="user", source=source, capability_id=capability_id, old_value=old, new_value=locked, reason=reason, before=before, after=before + 1, result="lock_updated")
        return ChangeResult(True, "lock_updated", before + 1, locked)


def restore_user_setting(uid: str, char_id: str, *, capability_id: str, reason: str, source: str = "admin") -> ChangeResult:
    if registry.resolve(capability_id) is None or not _reason(reason): return ChangeResult(False, "invalid_request", store.load(uid, char_id)["revision"])
    with _MUTATION_LOCK:
        state = store.load(uid, char_id); before = int(state.get("revision") or 0); old = state.setdefault("agent_state", {}).pop(capability_id, None); state["revision"] = before + 1
        if not store.save(uid, char_id, state): return ChangeResult(False, "persistence_failed", before)
        _audit(uid, char_id, action_id=uuid.uuid4().hex, actor="user", source=source, capability_id=capability_id, old_value=old, new_value=None, reason=reason, before=before, after=before + 1, result="restored_user_setting")
        return ChangeResult(True, "restored_user_setting", before + 1)


def undo_latest_agent_change(uid: str, char_id: str, *, capability_id: str, reason: str, source: str = "admin") -> ChangeResult:
    if registry.resolve(capability_id) is None or not _reason(reason):
        return ChangeResult(False, "invalid_request", store.load(uid, char_id)["revision"])
    with _MUTATION_LOCK:
        state = store.load(uid, char_id); before = int(state.get("revision") or 0)
        record = next((item for item in reversed(store.read_audit(uid, char_id, limit=200)) if item.get("actor") == "agent" and item.get("result") == "applied" and item.get("capability_id") == capability_id), None)
        if record is None:
            return ChangeResult(False, "no_agent_change", before)
        old_value = record.get("old_value")
        current = state.setdefault("agent_state", {}).get(capability_id)
        if old_value is None:
            state["agent_state"].pop(capability_id, None)
        else:
            state["agent_state"][capability_id] = old_value
        state["revision"] = before + 1
        if not store.save(uid, char_id, state):
            return ChangeResult(False, "persistence_failed", before)
        _audit(uid, char_id, action_id=uuid.uuid4().hex, actor="user", source=source, capability_id=capability_id, old_value=current, new_value=old_value, reason=reason, before=before, after=before + 1, result="undid_agent_change")
        return ChangeResult(True, "undid_agent_change", before + 1, old_value)


def view(uid: str, char_id: str) -> dict[str, Any]:
    state = store.load(uid, char_id)
    rows = []
    known = ({item.capability_id for item in registry.list_available()} | set((state.get("grants") or {})) | set((state.get("agent_state") or {})) | set((state.get("locks") or {})))
    for capability_id in sorted(known):
        spec = registry.resolve(capability_id)
        if spec is None: continue
        available, selected = policy.effective(capability_id, uid, char_id)
        grant = (state.get("grants") or {}).get(capability_id)
        rows.append({"capability_id": capability_id, "kind": spec.kind, "system_available": policy.global_available(capability_id), "grant": grant, "agent_selected_state": (state.get("agent_state") or {}).get(capability_id), "locked": bool((state.get("locks") or {}).get(capability_id, False)), "effective": available, "effective_value": selected})
    return {"uid": str(uid), "char_id": str(char_id), "revision": int(state.get("revision") or 0), "capabilities": rows, "audit": list(reversed(store.read_audit(uid, char_id, limit=20)))}


def agent_gateway_context(uid: str, char_id: str) -> dict[str, Any] | None:
    """Return the safe, currently mutable capability summary for an agent loop."""
    snapshot = view(uid, char_id)
    mutable = []
    locked = []
    for row in snapshot["capabilities"]:
        grant = row.get("grant") or {}
        if row.get("locked"):
            locked.append(row["capability_id"])
        allowed, _ = policy.can_agent_manage(uid, char_id, row["capability_id"])
        if not allowed:
            continue
        mutable.append({
            "id": row["capability_id"],
            "agent_selected_state": row.get("agent_selected_state"),
            "effective": bool(row.get("effective")),
            "effective_value": row.get("effective_value"),
            "constraints": grant.get("constraints") or {},
            "locked": bool(row.get("locked")),
        })
    if not mutable:
        return None
    return {"revision": snapshot["revision"], "mutable_capabilities": mutable, "locked_capabilities": locked}
