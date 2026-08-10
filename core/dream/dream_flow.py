"""
Dream flow entries — rule-driven "what's happening" ticker for the frontend
dream sidebar (`flow_entries`).

Zero extra LLM calls: entries are derived purely from state deltas already
computed by dream_pipeline / dream_state. Pure functions only (no I/O) — the
caller is responsible for read_state/write_state around these helpers.

Never writes character names into summary text (uses "他", matching the
existing frontend fallback copy) — this keeps the ticker free of hardcoded
character identity by construction.
"""

from datetime import datetime, timezone
from typing import Any

_MAX_ENTRIES = 10
_MAX_PER_ROUND = 2
_TENSION_DELTA_MIN = 0.15

_STATUS_SHIFT_SUMMARIES: dict[str, str] = {
    "enter": "梦境正在成形",
    "exit_requested": "醒来的边缘在靠近",
    "closing": "梦在慢慢消散",
    "retained": "他把你留了下来",
    "resumed": "你决定再留一会儿",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def append_flow_entry(state: dict[str, Any], kind: str, summary: str) -> dict[str, Any]:
    """Return a new state dict with one flow entry appended (FIFO, cap _MAX_ENTRIES)."""
    entries = list(state.get("flow_entries") or [])
    entries.append({"ts": _now_iso(), "kind": kind, "summary": summary})
    if len(entries) > _MAX_ENTRIES:
        entries = entries[-_MAX_ENTRIES:]
    return {**state, "flow_entries": entries}


def append_status_shift(state: dict[str, Any], event: str) -> dict[str, Any]:
    """Convenience wrapper for the status_shift kind using the canned summary table."""
    summary = _STATUS_SHIFT_SUMMARIES.get(event)
    if not summary:
        return state
    return append_flow_entry(state, "status_shift", summary)


def clear_flow_entries(state: dict[str, Any]) -> dict[str, Any]:
    """Reset flow_entries to an empty list (called at /dream/enter)."""
    return {**state, "flow_entries": []}


def generate_flow_entries(
    prev_state: dict[str, Any],
    new_state: dict[str, Any],
) -> list[tuple[str, str]]:
    """
    Diff prev/new dream-local state and return up to _MAX_PER_ROUND
    (kind, summary) tuples, in priority order: scene_shift, tension_up/down,
    anchor_new. (status_shift is handled separately via append_status_shift,
    since it's driven by explicit transitions, not state diffing.)
    """
    hits: list[tuple[str, str]] = []

    prev_scene = prev_state.get("scene_state")
    new_scene = new_state.get("scene_state")
    if new_scene and new_scene != prev_scene:
        hits.append(("scene_shift", f"场景转入：{str(new_scene)[:20]}"))

    prev_tension = float(prev_state.get("emotional_tension") or 0.0)
    new_tension = float(new_state.get("emotional_tension") or 0.0)
    delta = new_tension - prev_tension
    if delta >= _TENSION_DELTA_MIN:
        hits.append(("tension_up", "他的情绪张力在上升"))
    elif -delta >= _TENSION_DELTA_MIN:
        hits.append(("tension_down", "他的情绪张力在回落"))

    prev_anchors = set(prev_state.get("symbolic_anchors") or [])
    new_anchors = list(new_state.get("symbolic_anchors") or [])
    for anchor in new_anchors:
        if anchor not in prev_anchors:
            hits.append(("anchor_new", f"新的象征浮现：{anchor}"))

    return hits[:_MAX_PER_ROUND]


def apply_flow_entries(state: dict[str, Any], hits: list[tuple[str, str]]) -> dict[str, Any]:
    """Fold a list of (kind, summary) hits into state via append_flow_entry."""
    for kind, summary in hits:
        state = append_flow_entry(state, kind, summary)
    return state
