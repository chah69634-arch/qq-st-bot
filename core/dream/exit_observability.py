"""Durable, text-free lifecycle records for Reality Dream-exit messages."""
from __future__ import annotations

import json
import logging
import time
from typing import Any

from core.data_paths import DEFAULT_CHAR_ID
from core.safe_write import safe_write_json
from core.sandbox import get_paths

logger = logging.getLogger(__name__)

WAITING_AFTERGLOW = "waiting_afterglow"
READY = "ready"
BLOCKED = "blocked"
SENT = "sent"
EXPIRED = "expired"
DELIVERY_SCHEDULED_GREETING = "scheduled_greeting"
DELIVERY_CONTINUATION = "continuation"
CONTINUATION_PENDING = "pending"
CONTINUATION_DEFERRED = "deferred"
CONTINUATION_SENT = "sent"
CONTINUATION_CANCELLED = "cancelled"
CONTINUATION_FAILED = "failed"
LIFECYCLES = frozenset({
    WAITING_AFTERGLOW, READY, BLOCKED, SENT, EXPIRED,
    CONTINUATION_PENDING, CONTINUATION_DEFERRED, CONTINUATION_SENT,
    CONTINUATION_CANCELLED, CONTINUATION_FAILED,
})

NOT_QUIET = "not_quiet"
DND = "dnd"
GLOBAL_GAP = "global_gap"
BUDGET = "budget"
HIGHER_PRIORITY_WINNER = "higher_priority_winner"
AFTERGLOW_NOT_READY = "afterglow_not_ready"
SEND_FAILED = "send_failed"
CONTINUATION_QUEUED = "continuation_queued"
NEW_USER_TURN = "new_user_turn"
ALREADY_GREETED = "already_greeted"
CLOSE_NOT_ELIGIBLE = "close_not_eligible"
PIPELINE_UNAVAILABLE = "pipeline_unavailable"
LLM_EMPTY = "llm_empty"
CONVERSATION_BUSY = "conversation_busy"
BLOCK_REASONS = frozenset({
    NOT_QUIET,
    DND,
    GLOBAL_GAP,
    BUDGET,
    HIGHER_PRIORITY_WINNER,
    AFTERGLOW_NOT_READY,
    SEND_FAILED,
    CONTINUATION_QUEUED,
    NEW_USER_TURN,
    ALREADY_GREETED,
    CLOSE_NOT_ELIGIBLE,
    PIPELINE_UNAVAILABLE,
    LLM_EMPTY,
    CONVERSATION_BUSY,
})


def _path(char_id: str) -> Any:
    return get_paths().dreams_exit_lifecycle_path(char_id=char_id)


def _load(char_id: str) -> list[dict[str, Any]]:
    path = _path(char_id)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return [item for item in data if isinstance(item, dict)] if isinstance(data, list) else []
    except Exception as exc:
        logger.warning("[dream_exit_observability] unreadable lifecycle: %s", exc)
        return []


def _save(char_id: str, rows: list[dict[str, Any]]) -> bool:
    return safe_write_json(_path(char_id), rows[-200:])


def _safe_row(row: dict[str, Any]) -> dict[str, Any]:
    lifecycle = str(row.get("lifecycle") or WAITING_AFTERGLOW)
    if lifecycle not in LIFECYCLES:
        lifecycle = WAITING_AFTERGLOW
    reason = str(row.get("reason_code") or "")
    if reason and reason not in BLOCK_REASONS:
        reason = ""
    delivery_kind = str(row.get("delivery_kind") or DELIVERY_SCHEDULED_GREETING)
    if delivery_kind not in {DELIVERY_SCHEDULED_GREETING, DELIVERY_CONTINUATION}:
        delivery_kind = DELIVERY_SCHEDULED_GREETING
    try:
        attempts = max(0, int(row.get("attempts") or 0))
    except (TypeError, ValueError):
        attempts = 0
    return {
        "dream_id": str(row.get("dream_id") or "")[:160],
        "uid": str(row.get("uid") or "")[:160],
        "char_id": str(row.get("char_id") or DEFAULT_CHAR_ID)[:160],
        "delivery_kind": delivery_kind,
        "lifecycle": lifecycle,
        "reason_code": reason,
        "created_at": float(row.get("created_at") or time.time()),
        "ready_at": row.get("ready_at"),
        "last_attempt_at": row.get("last_attempt_at"),
        "sent_at": row.get("sent_at"),
        "expires_at": row.get("expires_at"),
        "attempts": attempts,
        "last_error": str(row.get("last_error") or "")[:120],
    }


def record(
    uid: str,
    dream_id: str,
    *,
    char_id: str = DEFAULT_CHAR_ID,
    delivery_kind: str = DELIVERY_SCHEDULED_GREETING,
    lifecycle: str,
    reason_code: str = "",
    expires_at: float | None = None,
    last_error: str = "",
) -> dict[str, Any]:
    """Upsert one bounded record and return the sanitized row."""
    rows = _load(char_id)
    now = time.time()
    delivery_kind = str(delivery_kind or DELIVERY_SCHEDULED_GREETING)
    index = next(
        (
            i for i, item in enumerate(rows)
            if str(item.get("dream_id")) == str(dream_id)
            and str(item.get("uid")) == str(uid)
            and str(item.get("delivery_kind") or DELIVERY_SCHEDULED_GREETING) == delivery_kind
        ),
        None,
    )
    previous = rows[index] if index is not None else {}
    row = _safe_row({
        **previous,
        "uid": uid,
        "dream_id": dream_id,
        "char_id": char_id,
        "delivery_kind": delivery_kind,
        "lifecycle": lifecycle,
        "reason_code": reason_code,
        "expires_at": expires_at if expires_at is not None else previous.get("expires_at"),
        "last_error": last_error,
    })
    if lifecycle == READY and not row.get("ready_at"):
        row["ready_at"] = now
    if lifecycle in {BLOCKED, SENT, CONTINUATION_DEFERRED, CONTINUATION_SENT,
                     CONTINUATION_CANCELLED, CONTINUATION_FAILED}:
        row["last_attempt_at"] = now
        row["attempts"] = int(previous.get("attempts") or 0) + 1
    if lifecycle in {SENT, CONTINUATION_SENT}:
        row["sent_at"] = now
        row["reason_code"] = ""
        row["last_error"] = ""
    if index is None:
        rows.append(row)
    else:
        rows[index] = row
    _save(char_id, rows)
    return row


def list_records(
    *,
    char_id: str = DEFAULT_CHAR_ID,
    limit: int = 50,
    delivery_kind: str | None = None,
) -> list[dict[str, Any]]:
    rows = _load(char_id)
    safe_rows = [_safe_row(row) for row in rows]
    if delivery_kind is not None:
        safe_rows = [row for row in safe_rows if row.get("delivery_kind") == str(delivery_kind)]
    return safe_rows[-max(1, min(int(limit), 200)):][::-1]


def get_record(
    dream_id: str,
    *,
    char_id: str = DEFAULT_CHAR_ID,
    delivery_kind: str | None = None,
) -> dict[str, Any] | None:
    for row in list_records(char_id=char_id, limit=200, delivery_kind=delivery_kind):
        if row.get("dream_id") == str(dream_id):
            return row
    return None
