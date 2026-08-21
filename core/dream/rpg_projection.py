"""Pure event-ledger projections for RPG Dream sessions."""

from __future__ import annotations

from typing import Any


def _branch_limits(events: list[dict[str, Any]], active_branch_id: str) -> dict[str, int | None]:
    metadata: dict[str, tuple[str | None, int | None]] = {"root": (None, None)}
    for event in events:
        if event.get("event_type") == "branch_created":
            payload = event.get("payload") or {}
            branch_id = payload.get("new_branch_id")
            if isinstance(branch_id, str):
                metadata[branch_id] = (payload.get("parent_branch_id"), payload.get("base_seq"))
    limits: dict[str, int | None] = {}
    branch = active_branch_id
    limit: int | None = None
    while branch and branch not in limits:
        limits[branch] = limit
        parent, base_seq = metadata.get(branch, (None, None))
        branch = parent or ""
        limit = base_seq if isinstance(base_seq, int) else None
    return limits


def events_for_branch(events: list[dict[str, Any]], active_branch_id: str) -> list[dict[str, Any]]:
    limits = _branch_limits(events, active_branch_id)
    result = []
    for event in events:
        branch = event.get("branch_id")
        seq = event.get("seq")
        if branch not in limits or not isinstance(seq, int):
            continue
        maximum = limits[branch]
        if maximum is None or seq <= maximum:
            result.append(event)
    return sorted(result, key=lambda item: int(item.get("seq", 0)))


def derive_snapshot(events: list[dict[str, Any]], *, active_branch_id: str | None, revision: int) -> dict[str, Any]:
    branch_id = active_branch_id or "root"
    facts: dict[str, dict[str, dict[str, Any]]] = {scope: {} for scope in ("public", "player", "character", "kp_private")}
    scene: dict[str, str] = {}
    for event in events_for_branch(events, branch_id):
        projections = event.get("projections") or {}
        for scope, target in facts.items():
            for fact in projections.get(scope) or []:
                if isinstance(fact, dict) and isinstance(fact.get("fact_id"), str):
                    target[fact["fact_id"]] = {"value": fact.get("value", ""), "knowledge": fact.get("knowledge")}
        for update in event.get("scene_updates") or []:
            if isinstance(update, dict) and isinstance(update.get("key"), str):
                scene[update["key"]] = str(update.get("value", ""))
    return {
        "schema_version": 1,
        "active_branch_id": branch_id,
        "scene_revision": revision,
        "scene": scene,
        "shared_facts": facts["public"],
        "player_known_facts": facts["player"],
        "character_knowledge": facts["character"],
        "kp_private_facts": facts["kp_private"],
    }
