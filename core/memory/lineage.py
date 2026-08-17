"""Deterministic lineage helpers for derived memory products.

Lineage is evidence-only: this module never matches summaries or invents an
event relationship. Missing or legacy evidence is reported as
``legacy_unknown``.
"""
from __future__ import annotations

from typing import Any, Iterable

from core.memory import episodic_memory, event_query, mid_term, storyline
from core.memory.scope import MemoryScope

MAX_SOURCE_EVENT_IDS = 200


def normalize_source_event_ids(value: object) -> list[str]:
    if not isinstance(value, (list, tuple, set)):
        return []
    result: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str):
            continue
        item = item.strip()
        if item and item not in seen:
            seen.add(item)
            result.append(item)
            if len(result) >= MAX_SOURCE_EVENT_IDS:
                break
    return result


def event_ids_for_turn(turn_id: str, *, is_trigger_turn: bool = False) -> list[str]:
    """Return the stable event IDs emitted by ``capture_turn``."""
    if not turn_id:
        return []
    return [f"{turn_id}:assistant"] if is_trigger_turn else [
        f"{turn_id}:user", f"{turn_id}:assistant"
    ]


def _resolve_events(scope: MemoryScope, source_ids: Iterable[str]) -> tuple[list[dict], str]:
    ids = normalize_source_event_ids(list(source_ids))
    if not ids:
        return [], "legacy_unknown"
    events: list[dict] = []
    missing = False
    for event_id in ids:
        event = event_query.get_event(scope, event_id)
        if event is None:
            missing = True
            events.append({"event_id": event_id, "status": "missing"})
        else:
            events.append(event)
    return events, "legacy_unknown" if missing else "resolved"


def resolve_episode(uid: str, episode_id: str, *, char_id: str) -> dict[str, Any] | None:
    episode = next((e for e in episodic_memory._load_memories(uid, char_id=char_id)
                    if e.get("id") == episode_id), None)
    if episode is None:
        return None
    source_ids = normalize_source_event_ids(episode.get("source_event_ids"))
    events, status = _resolve_events(MemoryScope.reality_scope(str(uid), char_id), source_ids)
    return {
        "artifact": "episodic",
        "id": episode_id,
        "source_event_ids": source_ids,
        "events": events,
        "lineage_status": status,
    }


def resolve_storyline_node(uid: str, arc_id: str, node_id: str, *, char_id: str) -> dict[str, Any] | None:
    data = storyline.load(uid, char_id=char_id)
    arc = next((a for a in data.get("arcs", []) if a.get("arc_id") == arc_id), None)
    node = next((n for n in (arc or {}).get("nodes", []) if n.get("node_id") == node_id), None)
    if arc is None or node is None:
        return None
    source_ids = normalize_source_event_ids(node.get("source_ids"))
    events, status = _resolve_events(MemoryScope.reality_scope(str(uid), char_id), source_ids)
    return {
        "artifact": "storyline_node",
        "arc_id": arc_id,
        "node_id": node_id,
        "source_event_ids": source_ids,
        "events": events,
        "lineage_status": status,
    }


def dry_run(uid: str, *, char_id: str) -> dict[str, Any]:
    """Report deterministic backfill candidates without modifying any file."""
    scope = MemoryScope.reality_scope(str(uid), char_id)
    mids = mid_term.load(uid, char_id=char_id)
    episodes = episodic_memory._load_memories(uid, char_id=char_id)
    mid_candidates = 0
    episode_candidates = 0
    legacy_unknown = 0
    for entry in mids:
        if entry.get("source_event_ids"):
            continue
        ids = event_ids_for_turn(str(entry.get("source_turn_id") or ""),
                                 is_trigger_turn=bool(entry.get("is_trigger_turn")))
        if ids and all(event_query.get_event(scope, event_id) is not None for event_id in ids):
            mid_candidates += 1
        else:
            legacy_unknown += 1
    mid_by_id = {str(e.get("mid_id")): e for e in mids if e.get("mid_id")}
    for episode in episodes:
        if episode.get("source_event_ids"):
            continue
        ids: list[str] = []
        unknown = False
        for mid_id in episode.get("source_mid_ids") or []:
            source = mid_by_id.get(str(mid_id))
            if source is None:
                unknown = True
                break
            ids.extend(event_ids_for_turn(str(source.get("source_turn_id") or ""),
                                          is_trigger_turn=bool(source.get("is_trigger_turn"))))
        ids = normalize_source_event_ids(ids)
        if not unknown and ids and all(event_query.get_event(scope, event_id) is not None for event_id in ids):
            episode_candidates += 1
        else:
            legacy_unknown += 1
    return {
        "uid": str(uid),
        "char_id": char_id,
        "dry_run": True,
        "mid_term_backfill_candidates": mid_candidates,
        "episodic_backfill_candidates": episode_candidates,
        "legacy_unknown": legacy_unknown,
        "storyline_nodes": "append_only_no_backfill",
    }
