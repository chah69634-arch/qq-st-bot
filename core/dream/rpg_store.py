"""Atomic persistence and redacted projections for RPG Dream sessions."""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

from core.data_paths import DEFAULT_CHAR_ID, safe_user_id
from core.safe_write import safe_append_jsonl, safe_write_json
from core.sandbox import get_paths
from core.dream.rpg_models import RpgCore, RPG_SESSION_CLOSED, RPG_SESSION_UNCERTAIN


def _path(uid: str | int, dream_id: str, *, char_id: str = DEFAULT_CHAR_ID):
    return get_paths().dream_rpg_session_path(uid, dream_id, char_id=char_id)


def session_dir(uid: str | int, dream_id: str, *, char_id: str = DEFAULT_CHAR_ID) -> Path:
    """All RPG artifacts stay beside the registered session.json path."""
    return _path(uid, dream_id, char_id=char_id).parent


def events_path(uid: str | int, dream_id: str, *, char_id: str = DEFAULT_CHAR_ID) -> Path:
    return session_dir(uid, dream_id, char_id=char_id) / "events.jsonl"


def dice_path(uid: str | int, dream_id: str, *, char_id: str = DEFAULT_CHAR_ID) -> Path:
    return session_dir(uid, dream_id, char_id=char_id) / "dice.jsonl"


def snapshot_path(uid: str | int, dream_id: str, *, char_id: str = DEFAULT_CHAR_ID) -> Path:
    return session_dir(uid, dream_id, char_id=char_id) / "snapshot.json"


def receipts_path(uid: str | int, dream_id: str, *, char_id: str = DEFAULT_CHAR_ID) -> Path:
    return session_dir(uid, dream_id, char_id=char_id) / "receipts.json"


def transcript_path(uid: str | int, dream_id: str, *, char_id: str = DEFAULT_CHAR_ID) -> Path:
    return session_dir(uid, dream_id, char_id=char_id) / "transcript.jsonl"


def turn_receipts_path(uid: str | int, dream_id: str, *, char_id: str = DEFAULT_CHAR_ID) -> Path:
    return session_dir(uid, dream_id, char_id=char_id) / "turn_receipts.json"


def kernel_stats_path(uid: str | int, dream_id: str, *, char_id: str = DEFAULT_CHAR_ID) -> Path:
    return session_dir(uid, dream_id, char_id=char_id) / "kernel_stats.json"


def record_kernel_stat(uid: str | int, dream_id: str, key: str, *, char_id: str = DEFAULT_CHAR_ID) -> None:
    """Best-effort content-free counter used only by RPG observability."""
    if key not in {"invalid_proposal_count", "recovery_conflict_count"}:
        return
    path = kernel_stats_path(uid, dream_id, char_id=char_id)
    try:
        raw = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        stats = raw if isinstance(raw, dict) else {}
        stats[key] = int(stats.get(key, 0)) + 1
        safe_write_json(path, stats)
    except Exception:
        return


def load_kernel_stats(uid: str | int, dream_id: str, *, char_id: str = DEFAULT_CHAR_ID) -> dict[str, int]:
    try:
        raw = json.loads(kernel_stats_path(uid, dream_id, char_id=char_id).read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(raw, dict):
        return {}
    return {key: value for key, value in raw.items() if key in {"invalid_proposal_count", "recovery_conflict_count"} and isinstance(value, int) and value >= 0}


def create(core: RpgCore) -> bool:
    path = _path(core.owner_uid, core.dream_id, char_id=core.char_id)
    return not path.exists() and safe_write_json(path, core.to_dict(), keep_bak=False)


def save(core: RpgCore, *, expected_revision: int | None = None) -> tuple[bool, str]:
    """Persist a core only if its durable revision remains expected."""
    current, health = load(core.owner_uid, core.dream_id, char_id=core.char_id)
    if current is None:
        return False, health
    if expected_revision is not None and current.scene_revision != expected_revision:
        return False, "revision_conflict"
    return (True, "ok") if safe_write_json(_path(core.owner_uid, core.dream_id, char_id=core.char_id), core.to_dict()) else (False, "write_failed")


def append_event(uid: str | int, dream_id: str, event: dict[str, Any], *, char_id: str = DEFAULT_CHAR_ID) -> bool:
    return safe_append_jsonl(events_path(uid, dream_id, char_id=char_id), event)


def append_dice(uid: str | int, dream_id: str, record: dict[str, Any], *, char_id: str = DEFAULT_CHAR_ID) -> bool:
    return safe_append_jsonl(dice_path(uid, dream_id, char_id=char_id), record)


def append_transcript(uid: str | int, dream_id: str, entry: dict[str, Any], *, char_id: str = DEFAULT_CHAR_ID) -> bool:
    return safe_append_jsonl(transcript_path(uid, dream_id, char_id=char_id), entry)


def read_jsonl_with_health(path: Path) -> tuple[list[dict[str, Any]], str]:
    """Read an append-only ledger without treating corruption as an empty log."""
    if not path.exists():
        return [], "missing"
    result: list[dict[str, Any]] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                item = json.loads(line)
                if not isinstance(item, dict):
                    return [], "invalid"
                result.append(item)
    except Exception:
        return [], "invalid"
    return result, "ok"


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    """Compatibility reader for diagnostics; mutation paths must use health."""
    return read_jsonl_with_health(path)[0]


def read_transcript(uid: str | int, dream_id: str, *, char_id: str = DEFAULT_CHAR_ID) -> tuple[list[dict[str, Any]], bool]:
    rows, health = read_jsonl_with_health(transcript_path(uid, dream_id, char_id=char_id))
    return rows, health == "invalid"


def load_turn_receipts(uid: str | int, dream_id: str, *, char_id: str = DEFAULT_CHAR_ID) -> dict[str, dict[str, Any]]:
    path = turn_receipts_path(uid, dream_id, char_id=char_id)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def save_turn_receipts(uid: str | int, dream_id: str, receipts: dict[str, dict[str, Any]], *, char_id: str = DEFAULT_CHAR_ID) -> bool:
    return safe_write_json(turn_receipts_path(uid, dream_id, char_id=char_id), receipts)


def read_events(uid: str | int, dream_id: str, *, char_id: str = DEFAULT_CHAR_ID) -> list[dict[str, Any]]:
    return read_jsonl(events_path(uid, dream_id, char_id=char_id))


def read_events_with_health(uid: str | int, dream_id: str, *, char_id: str = DEFAULT_CHAR_ID) -> tuple[list[dict[str, Any]], str]:
    events, health = read_jsonl_with_health(events_path(uid, dream_id, char_id=char_id))
    if health != "ok":
        return events, health
    seen_seq: set[int] = set()
    for event in events:
        core_after = event.get("core_after")
        seq, revision = event.get("seq"), event.get("revision")
        if (
            event.get("dream_id") != dream_id
            or not isinstance(event.get("event_id"), str)
            or not isinstance(event.get("request_id"), str)
            or not isinstance(event.get("request_digest"), str)
            or not isinstance(event.get("branch_id"), str)
            or not isinstance(seq, int) or seq < 1 or seq in seen_seq
            or not isinstance(revision, int) or revision < 1
            or not isinstance(core_after, dict)
            or core_after.get("scene_revision") != revision
        ):
            return [], "invalid"
        seen_seq.add(seq)
    return events, "ok"


def read_dice(uid: str | int, dream_id: str, *, char_id: str = DEFAULT_CHAR_ID) -> list[dict[str, Any]]:
    return read_jsonl(dice_path(uid, dream_id, char_id=char_id))


def read_dice_with_health(uid: str | int, dream_id: str, *, char_id: str = DEFAULT_CHAR_ID) -> tuple[list[dict[str, Any]], str]:
    dice, health = read_jsonl_with_health(dice_path(uid, dream_id, char_id=char_id))
    if health != "ok":
        return dice, health
    seen_requests: set[str] = set()
    for record in dice:
        request_id = record.get("request_id")
        if (
            record.get("dream_id") != dream_id
            or not isinstance(request_id, str) or request_id in seen_requests
            or not isinstance(record.get("proposal_digest"), str)
            or not isinstance(record.get("seed"), str)
            or not isinstance(record.get("nonce"), str)
            or not isinstance(record.get("faces"), list)
            or not isinstance(record.get("total"), int)
            or not isinstance(record.get("outcome"), str)
        ):
            return [], "invalid"
        seen_requests.add(request_id)
    return dice, "ok"


def load_receipts(uid: str | int, dream_id: str, *, char_id: str = DEFAULT_CHAR_ID) -> dict[str, dict[str, Any]]:
    return load_receipts_with_health(uid, dream_id, char_id=char_id)[0]


def load_receipts_with_health(uid: str | int, dream_id: str, *, char_id: str = DEFAULT_CHAR_ID) -> tuple[dict[str, dict[str, Any]], str]:
    path = receipts_path(uid, dream_id, char_id=char_id)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}, "missing"
    except Exception:
        return {}, "invalid"
    if not isinstance(data, dict) or not all(
        isinstance(key, str)
        and isinstance(value, dict)
        and isinstance(value.get("proposal_digest"), str)
        and value.get("status") in {"pending", "committed"}
        for key, value in data.items()
    ):
        return {}, "invalid"
    return data, "ok"


def save_receipts(uid: str | int, dream_id: str, receipts: dict[str, dict[str, Any]], *, char_id: str = DEFAULT_CHAR_ID) -> bool:
    return safe_write_json(receipts_path(uid, dream_id, char_id=char_id), receipts)


def load(uid: str | int, dream_id: str, *, char_id: str = DEFAULT_CHAR_ID) -> tuple[RpgCore | None, str]:
    try:
        core = RpgCore.from_dict(json.loads(_path(uid, dream_id, char_id=char_id).read_text(encoding="utf-8")))
    except FileNotFoundError:
        return None, "missing"
    except Exception:
        return None, "invalid"
    if core.owner_uid != safe_user_id(uid) or core.dream_id != dream_id or core.char_id != char_id:
        return None, "invalid"
    return core, "ok"


def close(uid: str | int, dream_id: str, *, char_id: str = DEFAULT_CHAR_ID) -> tuple[RpgCore | None, str]:
    core, health = load(uid, dream_id, char_id=char_id)
    if core is None or core.status == RPG_SESSION_CLOSED:
        return core, health
    closed = replace(core, status=RPG_SESSION_CLOSED, updated_at=time.time())
    return (closed, "ok") if safe_write_json(_path(uid, dream_id, char_id=char_id), closed.to_dict()) else (None, "write_failed")


def mark_uncertain(uid: str | int, dream_id: str, *, char_id: str = DEFAULT_CHAR_ID, error_code: str) -> None:
    core, health = load(uid, dream_id, char_id=char_id)
    if core and health == "ok":
        safe_write_json(_path(uid, dream_id, char_id=char_id), replace(core, status=RPG_SESSION_UNCERTAIN, updated_at=time.time(), last_error_code=error_code).to_dict())


def projection(core: RpgCore | None, *, health: str, since: float | None = None) -> dict | None:
    if core is None:
        return None
    return {"dream_id": core.dream_id, "char_id": core.char_id, "script_id": core.script_id,
            "status": core.status, "round_status": core.round_status, "active_round_id": core.active_round_id,
            "active_branch_id": core.active_branch_id, "scene_revision": core.scene_revision,
            "since": since or core.created_at, "last_error_code": core.last_error_code, "session_health": health}


def observability(core: RpgCore | None, *, health: str, recovery_source: str) -> dict:
    token = lambda value: hashlib.sha256(value.encode("utf-8")).hexdigest()[:12] if value else None
    events, events_health = read_events_with_health(core.owner_uid, core.dream_id, char_id=core.char_id) if core else ([], "missing")
    dice, dice_health = read_dice_with_health(core.owner_uid, core.dream_id, char_id=core.char_id) if core else ([], "missing")
    receipts, receipts_health = load_receipts_with_health(core.owner_uid, core.dream_id, char_id=core.char_id) if core else ({}, "missing")
    stats = load_kernel_stats(core.owner_uid, core.dream_id, char_id=core.char_id) if core else {}
    ledger_health = "invalid" if "invalid" in {events_health, dice_health, receipts_health} else health
    branches = {event.get("branch_id") for event in events if isinstance(event.get("branch_id"), str)}
    branches.update((event.get("payload") or {}).get("new_branch_id") for event in events if event.get("event_type") == "branch_created")
    return {"session_count": int(core is not None), "active_session_count": int(bool(core and core.status == "active")),
            "round_count": max(0, core.next_round_seq - 1) if core else 0, "status": core.status if core else "none",
            "round_status": core.round_status if core else "none", "last_error_code": core.last_error_code if core else "RPG_SESSION_" + health.upper(),
            "recovery_source": recovery_source, "last_updated_at": core.updated_at if core else None, "path_health": ledger_health,
            "dream_id_hash": token(core.dream_id if core else None), "char_id_hash": token(core.char_id if core else None),
            "event_count": len(events), "dice_count": len(dice), "branch_count": len(branches - {None}),
            "pending_receipt_count": sum(1 for row in receipts.values() if row.get("status") == "pending"),
            "recovery_conflict_count": stats.get("recovery_conflict_count", 0),
            "invalid_proposal_count": stats.get("invalid_proposal_count", 0), "latency_bucket": "not_measured"}
