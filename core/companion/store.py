"""Durable, metadata-only companion receipts and session state."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from core.safe_write import safe_write_json
from core.sandbox import get_paths

logger = logging.getLogger(__name__)

RETENTION_SECONDS = 30 * 24 * 60 * 60
MAX_RECEIPTS_PER_CALLER = 1000
CALLER_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

_CALLER_LOCKS: dict[str, asyncio.Lock] = {}
_CALLER_LOCKS_GUARD = asyncio.Lock()


class CompanionStoreError(RuntimeError):
    """The metadata store could not establish a safe state."""


class CompanionSessionMismatch(ValueError):
    pass


class CompanionReceiptConflict(ValueError):
    pass


class CompanionReceiptUncertain(RuntimeError):
    pass


def validate_caller_label(value: object) -> str:
    if not isinstance(value, str) or not CALLER_RE.fullmatch(value):
        raise ValueError("invalid companion caller label")
    return value


def receipt_key(session_id: str, event_id: str) -> str:
    raw = f"{session_id}\0{event_id}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def request_digest(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def opaque_hash(value: object) -> str:
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:16]


def _created_timestamp(value: str) -> float:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.timestamp()


async def caller_lock(caller_label: str) -> asyncio.Lock:
    caller_label = validate_caller_label(caller_label)
    async with _CALLER_LOCKS_GUARD:
        return _CALLER_LOCKS.setdefault(caller_label, asyncio.Lock())


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, ValueError, TypeError):
        return None
    return value if isinstance(value, dict) else None


def _write(path: Path, value: dict[str, Any]) -> None:
    if not safe_write_json(path, value, keep_bak=False):
        raise CompanionStoreError("companion metadata write failed")


def _load_stats() -> dict[str, Any]:
    value = _read_json(get_paths().companion_stats())
    if not value:
        return {
            "received": 0,
            "by_kind_status": {},
            "by_error_code": {},
            "last_prune_at": None,
            "last_prune_removed": 0,
            "pruned_total": 0,
        }
    return value


def _write_stats(stats: dict[str, Any]) -> None:
    _write(get_paths().companion_stats(), stats)


def _increment_outcome(*, kind: str, status: str, error_code: str | None = None) -> None:
    stats = _load_stats()
    stats["received"] = int(stats.get("received") or 0) + 1
    by_kind_status = stats.setdefault("by_kind_status", {})
    kind_counts = by_kind_status.setdefault(kind, {})
    kind_counts[status] = int(kind_counts.get(status) or 0) + 1
    if error_code:
        by_error = stats.setdefault("by_error_code", {})
        by_error[error_code] = int(by_error.get(error_code) or 0) + 1
    _write_stats(stats)


async def reserve(
    *,
    caller_label: str,
    session_id: str,
    event_id: str,
    created_at: str,
    kind: str,
    digest: str,
) -> dict[str, Any]:
    """Advance the caller session and reserve a receipt as ``running``.

    The caller lock serializes session advancement and idempotency reservation,
    so concurrent requests cannot both observe an empty slot.
    """
    caller_label = validate_caller_label(caller_label)
    key = receipt_key(session_id, event_id)
    lock = await caller_lock(caller_label)
    async with lock:
        _prune_locked(caller_label)
        session_path = get_paths().companion_session(caller_label=caller_label)
        current = _read_json(session_path)
        created_ts = _created_timestamp(created_at)
        if current is None:
            _write(session_path, {
                "caller": caller_label,
                "session_id": session_id,
                "created_at": created_at,
                "created_ts": created_ts,
                "updated_at": time.time(),
            })
        elif current.get("session_id") != session_id:
            current_ts = float(current.get("created_ts") or 0.0)
            if created_ts <= current_ts:
                raise CompanionSessionMismatch("companion session is no longer current")
            _write(session_path, {
                "caller": caller_label,
                "session_id": session_id,
                "created_at": created_at,
                "created_ts": created_ts,
                "updated_at": time.time(),
            })

        path = get_paths().companion_receipt(caller_label=caller_label, receipt_key=key)
        existing = _read_json(path)
        if existing is not None:
            if existing.get("request_hash") != digest:
                raise CompanionReceiptConflict("companion idempotency payload conflict")
            status = str(existing.get("status") or "")
            if status == "running":
                return existing
            return existing

        row = {
            "caller": caller_label,
            "session_id": session_id,
            "event_id": event_id,
            "request_hash": digest,
            "kind": kind,
            "status": "running",
            "created_at": created_at,
            "created_ts": created_ts,
            "started_at": time.time(),
            "updated_at": time.time(),
        }
        _write(path, row)
        row["_new_reservation"] = True
        return row


async def complete(
    *,
    caller_label: str,
    session_id: str,
    event_id: str,
    result_status: str,
    reply_generated: bool,
    latency_ms: int,
    error_code: str | None = None,
) -> dict[str, Any]:
    caller_label = validate_caller_label(caller_label)
    key = receipt_key(session_id, event_id)
    lock = await caller_lock(caller_label)
    async with lock:
        path = get_paths().companion_receipt(caller_label=caller_label, receipt_key=key)
        row = _read_json(path)
        if row is None:
            raise CompanionStoreError("companion receipt disappeared")
        if row.get("status") != "running":
            return row
        row.update({
            "status": "completed",
            "result_status": result_status,
            "reply_generated": bool(reply_generated),
            "latency_ms": max(0, int(latency_ms)),
            "error_code": error_code,
            "finished_at": time.time(),
            "updated_at": time.time(),
        })
        _write(path, row)
        _increment_outcome(kind=str(row.get("kind") or "unknown"), status=result_status, error_code=error_code)
        return row


async def mark_failed(
    *,
    caller_label: str,
    session_id: str,
    event_id: str,
    error_code: str,
    latency_ms: int,
) -> dict[str, Any]:
    caller_label = validate_caller_label(caller_label)
    key = receipt_key(session_id, event_id)
    lock = await caller_lock(caller_label)
    async with lock:
        path = get_paths().companion_receipt(caller_label=caller_label, receipt_key=key)
        row = _read_json(path)
        if row is None:
            raise CompanionStoreError("companion receipt disappeared")
        row.update({
            "status": "failed",
            "result_status": None,
            "reply_generated": False,
            "latency_ms": max(0, int(latency_ms)),
            "error_code": error_code,
            "finished_at": time.time(),
            "updated_at": time.time(),
        })
        _write(path, row)
        _increment_outcome(kind=str(row.get("kind") or "unknown"), status="unavailable", error_code=error_code)
        return row


def record_duplicate(*, kind: str) -> None:
    _increment_outcome(kind=kind, status="duplicate")


def _prune_locked(caller_label: str) -> dict[str, int | float | None]:
    root = get_paths().companion_receipts_root() / caller_label
    if not root.exists():
        return {"removed": 0, "at": None}
    try:
        files = sorted(
            root.glob("*.json"),
            key=lambda path: path.stat().st_mtime if path.exists() else 0.0,
            reverse=True,
        )
    except OSError:
        return {"removed": 0, "at": None}
    cutoff = time.time() - RETENTION_SECONDS
    removable: list[Path] = []
    for path in files:
        row = _read_json(path)
        if row and row.get("status") == "running":
            continue
        removable.append(path)
    removed = 0
    for path in removable[MAX_RECEIPTS_PER_CALLER:]:
        try:
            path.unlink()
            removed += 1
        except OSError:
            pass
    for path in removable[:MAX_RECEIPTS_PER_CALLER]:
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink()
                removed += 1
        except OSError:
            pass
    if removed:
        stats = _load_stats()
        stats["last_prune_at"] = time.time()
        stats["last_prune_removed"] = removed
        stats["pruned_total"] = int(stats.get("pruned_total") or 0) + removed
        _write_stats(stats)
    return {"removed": removed, "at": time.time() if removed else None}


async def prune(caller_label: str) -> dict[str, int | float | None]:
    caller_label = validate_caller_label(caller_label)
    lock = await caller_lock(caller_label)
    async with lock:
        return _prune_locked(caller_label)


def _receipt_projection(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "timestamp": row.get("finished_at") or row.get("started_at") or row.get("updated_at"),
        "caller": row.get("caller"),
        "session_hash": opaque_hash(row.get("session_id") or ""),
        "event_hash": opaque_hash(row.get("event_id") or ""),
        "kind": row.get("kind"),
        "status": row.get("result_status") if row.get("status") == "completed" else row.get("status"),
        "error_code": row.get("error_code"),
        "latency_ms": row.get("latency_ms"),
        "reply_generated": bool(row.get("reply_generated")),
    }


def observability(*, is_inflight: Callable[[str, str], bool] | None = None) -> dict[str, Any]:
    """Return a bounded projection without body text, hashes, tokens, or paths."""
    paths = get_paths()
    sessions: list[dict[str, Any]] = []
    sessions_root = paths.companion_root() / "sessions"
    if sessions_root.exists():
        for path in sorted(sessions_root.glob("*.json")):
            row = _read_json(path)
            if not row:
                continue
            sessions.append({
                "caller": row.get("caller"),
                "session_hash": opaque_hash(row.get("session_id") or ""),
                "updated_at": row.get("updated_at"),
            })

    rows: list[dict[str, Any]] = []
    root = paths.companion_receipts_root()
    if root.exists():
        for caller_dir in root.iterdir():
            if not caller_dir.is_dir():
                continue
            for path in caller_dir.glob("*.json"):
                row = _read_json(path)
                if not row:
                    continue
                if row.get("status") == "running" and is_inflight is not None:
                    if not is_inflight(str(row.get("caller") or ""), str(row.get("event_id") or "")):
                        # The row remains running until an explicit resubmission; this
                        # makes a post-restart uncertain execution visible.
                        row = dict(row)
                        row["error_code"] = "execution_outcome_unknown"
                rows.append(row)
    rows.sort(key=lambda row: float(row.get("updated_at") or 0.0), reverse=True)
    bounded_rows = [_receipt_projection(row) for row in rows[:100]]
    running = sum(1 for row in rows if row.get("status") == "running")
    timestamps = [
        float(row.get("created_ts") or 0.0)
        for row in rows
        if row.get("created_ts") is not None
    ]
    stats = _load_stats()
    return {
        "contract": "presencekit-external-companion-v1",
        "runtime": {"available": True},
        "current_sessions": sessions,
        "counts": {
            "received": int(stats.get("received") or 0),
            "by_kind_status": stats.get("by_kind_status") or {},
            "by_error_code": stats.get("by_error_code") or {},
        },
        "recent": bounded_rows,
        "receipts": {
            "total": len(rows),
            "running": running,
            "oldest_created_at": min(timestamps) if timestamps else None,
            "latest_created_at": max(timestamps) if timestamps else None,
            "last_prune_at": stats.get("last_prune_at"),
            "last_prune_removed": int(stats.get("last_prune_removed") or 0),
            "pruned_total": int(stats.get("pruned_total") or 0),
        },
    }
