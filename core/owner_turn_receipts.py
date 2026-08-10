"""Metadata-only durable idempotency receipts for the owner turn API."""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from dataclasses import dataclass
from typing import Any

from core.safe_write import safe_write_json
from core.sandbox import get_paths

_RETENTION_SECONDS = 30 * 24 * 60 * 60
_MAX_RECEIPTS_PER_CALLER = 1000
_LOCKS: dict[tuple[str, str], asyncio.Lock] = {}
_LOCKS_GUARD = asyncio.Lock()


@dataclass(frozen=True)
class ReceiptResult:
    kind: str
    receipt: dict[str, Any] | None = None


def request_hash(*, message: str, reply_to: dict | None, upload_ids: list[str]) -> str:
    payload = {"message": message, "reply_to": reply_to, "upload_ids": list(upload_ids)}
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def receipt_key(client_turn_id: str) -> str:
    return hashlib.sha256(client_turn_id.encode("utf-8")).hexdigest()


async def lock_for(caller_label: str, client_turn_id: str) -> asyncio.Lock:
    key = (caller_label, receipt_key(client_turn_id))
    async with _LOCKS_GUARD:
        return _LOCKS.setdefault(key, asyncio.Lock())


def _path(caller_label: str, client_turn_id: str):
    return get_paths().owner_turn_receipt(
        caller_label=caller_label,
        receipt_key=receipt_key(client_turn_id),
    )


def load(caller_label: str, client_turn_id: str) -> dict[str, Any] | None:
    path = _path(caller_label, client_turn_id)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, ValueError, TypeError):
        return None
    return raw if isinstance(raw, dict) else None


def write(
    *,
    caller_label: str,
    client_turn_id: str,
    request_digest: str,
    status: str,
    canonical_turn_id: str | None = None,
    error_code: str | None = None,
    created_at: float | None = None,
) -> dict[str, Any]:
    now = time.time()
    row = {
        "caller": caller_label,
        "request_hash": request_digest,
        "status": status,
        "canonical_turn_id": canonical_turn_id,
        "created_at": created_at if created_at is not None else now,
        "updated_at": now,
        "error_code": error_code,
    }
    if not safe_write_json(_path(caller_label, client_turn_id), row):
        raise OSError("owner turn receipt write failed")
    return row


def projection(row: dict[str, Any]) -> dict[str, Any]:
    """Return only safe receipt fields for the status endpoint."""
    return {
        "status": row.get("status"),
        "canonical_turn_id": row.get("canonical_turn_id"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
        "error_code": row.get("error_code"),
    }


def prune() -> None:
    """Bound receipt retention without touching any user-authored data."""
    root = get_paths().owner_turn_receipts_root()
    if not root.exists():
        return
    cutoff = time.time() - _RETENTION_SECONDS
    for caller_dir in root.iterdir():
        if not caller_dir.is_dir():
            continue
        def _is_running(path) -> bool:
            try:
                row = json.loads(path.read_text(encoding="utf-8"))
            except (FileNotFoundError, OSError, ValueError, TypeError):
                return False
            return isinstance(row, dict) and row.get("status") == "running"

        try:
            files = sorted(
                caller_dir.glob("*.json"),
                key=lambda path: path.stat().st_mtime if path.exists() else 0,
                reverse=True,
            )
        except OSError:
            continue
        retained = [path for path in files if _is_running(path)]
        candidates = [path for path in files if path not in retained]
        for path in candidates[_MAX_RECEIPTS_PER_CALLER:]:
            try:
                path.unlink()
            except OSError:
                pass
        for path in candidates[:_MAX_RECEIPTS_PER_CALLER]:
            try:
                if path.stat().st_mtime < cutoff:
                    path.unlink()
            except OSError:
                pass
