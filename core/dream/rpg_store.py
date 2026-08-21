"""Atomic persistence and redacted projections for RPG Dream sessions."""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import replace

from core.data_paths import DEFAULT_CHAR_ID, safe_user_id
from core.safe_write import safe_write_json
from core.sandbox import get_paths
from core.dream.rpg_models import RpgCore, RPG_SESSION_CLOSED, RPG_SESSION_UNCERTAIN


def _path(uid: str | int, dream_id: str, *, char_id: str = DEFAULT_CHAR_ID):
    return get_paths().dream_rpg_session_path(uid, dream_id, char_id=char_id)


def create(core: RpgCore) -> bool:
    path = _path(core.owner_uid, core.dream_id, char_id=core.char_id)
    return not path.exists() and safe_write_json(path, core.to_dict(), keep_bak=False)


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
    return {"session_count": int(core is not None), "active_session_count": int(bool(core and core.status == "active")),
            "round_count": max(0, core.next_round_seq - 1) if core else 0, "status": core.status if core else "none",
            "round_status": core.round_status if core else "none", "last_error_code": core.last_error_code if core else "RPG_SESSION_" + health.upper(),
            "recovery_source": recovery_source, "last_updated_at": core.updated_at if core else None, "path_health": health,
            "dream_id_hash": token(core.dream_id if core else None), "char_id_hash": token(core.char_id if core else None)}
