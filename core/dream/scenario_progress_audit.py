"""Bounded, text-free Scenario progression audit records.

The ledger is an operations aid, not a transcript.  It deliberately stores only
safe stage/control identifiers and fixed dispositions so the management surface
can explain a turn without exposing user input, replies, authored script text, or
private truths.
"""
from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

from core.data_paths import DEFAULT_CHAR_ID, safe_user_id
from core.safe_write import safe_write_json
from core.sandbox import get_paths

logger = logging.getLogger(__name__)

MAX_RECORDS = 200
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_SAFE_CONTROL_ID_RE = re.compile(r"^[EB][1-9][0-9]{0,2}$")
_DISPOSITIONS = frozenset({
    "advanced",
    "completed",
    "no_progress",
    "control_missing",
    "control_invalid",
    "arc_blocked",
})
_CONTROL_STATUSES = frozenset({"valid", "missing", "invalid"})
_DETAIL_REASONS = frozenset({
    "arc_target_not_reached",
    "satisfied_without_valid_exit_sign",
    "stage_lookup_failed",
})


def _safe_id(value: Any) -> str:
    text = str(value or "").strip()
    return text if _SAFE_ID_RE.fullmatch(text) else ""


def _safe_control_ids(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = str(value or "").strip()
        if _SAFE_CONTROL_ID_RE.fullmatch(item) and item not in seen:
            result.append(item)
            seen.add(item)
    return result


def _nonnegative_int(value: Any, *, maximum: int = 1000000) -> int:
    try:
        return max(0, min(int(value or 0), maximum))
    except (TypeError, ValueError):
        return 0


def _safe_record(row: dict[str, Any]) -> dict[str, Any]:
    disposition = str(row.get("disposition") or "")
    if disposition not in _DISPOSITIONS:
        disposition = "control_invalid"
    status = str(row.get("control_status") or "")
    if status not in _CONTROL_STATUSES:
        status = "invalid"
    version = row.get("control_version")
    if version not in (1, 2):
        version = None
    detail_reason = str(row.get("detail_reason") or "")
    if detail_reason not in _DETAIL_REASONS:
        detail_reason = ""
    return {
        "dream_id": _safe_id(row.get("dream_id")),
        "char_id": _safe_id(row.get("char_id")) or DEFAULT_CHAR_ID,
        "time": float(row.get("time") or time.time()),
        "turn_index": _nonnegative_int(row.get("turn_index")),
        "prompt_profile": "scenario",
        "prompt_profile_version": "v2",
        "current_stage_id": _safe_id(row.get("current_stage_id")),
        "control_status": status,
        "control_version": version,
        "matched_exit_ids": _safe_control_ids(row.get("matched_exit_ids")),
        "blocked_ids": _safe_control_ids(row.get("blocked_ids")),
        "valid_exit_sign_count": _nonnegative_int(row.get("valid_exit_sign_count"), maximum=1000),
        "unknown_exit_sign_count": _nonnegative_int(row.get("unknown_exit_sign_count"), maximum=1000),
        "unknown_blocked_event_count": _nonnegative_int(row.get("unknown_blocked_event_count"), maximum=1000),
        "disposition": disposition,
        "reason": disposition,
        "detail_reason": detail_reason,
        "from_stage_id": _safe_id(row.get("from_stage_id")),
        "to_stage_id": _safe_id(row.get("to_stage_id")),
        "stall_turns": _nonnegative_int(row.get("stall_turns"), maximum=100000),
        "recovery_pending": bool(row.get("recovery_pending")),
    }


def _path(char_id: str) -> Any:
    return get_paths().dreams_scenario_progress_audit_path(char_id=safe_user_id(char_id))


def _load(char_id: str) -> list[dict[str, Any]]:
    try:
        path = _path(char_id)
        if not path.exists():
            return []
        data = json.loads(path.read_text(encoding="utf-8"))
        return [_safe_record(item) for item in data if isinstance(item, dict)] if isinstance(data, list) else []
    except Exception as exc:
        logger.warning("[scenario_progress_audit] unreadable ledger: %s", exc)
        return []


def record(
    dream_id: str,
    *,
    char_id: str = DEFAULT_CHAR_ID,
    turn_index: int = 0,
    current_stage_id: str = "",
    control_status: str = "missing",
    control_version: int | None = None,
    matched_exit_ids: list[str] | None = None,
    blocked_ids: list[str] | None = None,
    valid_exit_sign_count: int = 0,
    unknown_exit_sign_count: int = 0,
    unknown_blocked_event_count: int = 0,
    disposition: str = "control_invalid",
    detail_reason: str = "",
    from_stage_id: str = "",
    to_stage_id: str = "",
    stall_turns: int = 0,
    recovery_pending: bool = False,
) -> dict[str, Any]:
    """Append one sanitized row; all persistence errors are fail-open."""
    row = _safe_record({
        "dream_id": dream_id,
        "char_id": char_id,
        "time": time.time(),
        "turn_index": turn_index,
        "current_stage_id": current_stage_id,
        "control_status": control_status,
        "control_version": control_version,
        "matched_exit_ids": matched_exit_ids,
        "blocked_ids": blocked_ids,
        "valid_exit_sign_count": valid_exit_sign_count,
        "unknown_exit_sign_count": unknown_exit_sign_count,
        "unknown_blocked_event_count": unknown_blocked_event_count,
        "disposition": disposition,
        "detail_reason": detail_reason,
        "from_stage_id": from_stage_id,
        "to_stage_id": to_stage_id,
        "stall_turns": stall_turns,
        "recovery_pending": recovery_pending,
    })
    try:
        rows = _load(char_id)
        rows.append(row)
        safe_write_json(_path(char_id), rows[-MAX_RECORDS:])
    except Exception as exc:
        logger.warning("[scenario_progress_audit] write skipped: %s", exc)
    return row


def list_records(
    *,
    char_id: str = DEFAULT_CHAR_ID,
    dream_id: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Return newest-first bounded safe rows, optionally for one Dream."""
    try:
        rows = _load(char_id)
        wanted = _safe_id(dream_id) if dream_id else ""
        if wanted:
            rows = [row for row in rows if row.get("dream_id") == wanted]
        return rows[-max(1, min(int(limit), MAX_RECORDS)):][::-1]
    except Exception as exc:
        logger.warning("[scenario_progress_audit] read skipped: %s", exc)
        return []
