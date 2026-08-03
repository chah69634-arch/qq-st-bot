"""Durable, bounded Self Capability state and append-only audit writer."""
from __future__ import annotations

import json
import time
from copy import deepcopy
from typing import Any

from core.safe_write import safe_append_jsonl, safe_write_json
from core.sandbox import get_paths
from core.self_management.models import state_template

MAX_APPLIED_ACTIONS = 200


def _path(uid: str, char_id: str):
    return get_paths().self_management_state(uid, char_id=char_id)


def load(uid: str, char_id: str) -> dict[str, Any]:
    state = state_template(uid, char_id)
    try:
        path = _path(uid, char_id)
        if not path.exists():
            return state
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or raw.get("uid") != str(uid) or raw.get("char_id") != str(char_id):
            return state
        for key, default in state.items():
            value = raw.get(key)
            if isinstance(value, type(default)):
                state[key] = value
    except Exception:
        # Fail open preserves legacy tool behavior; a corrupt control file must
        # never make an unrelated character inherit another character's policy.
        return state_template(uid, char_id)
    return state


def exists(uid: str, char_id: str) -> bool:
    try:
        return _path(uid, char_id).exists()
    except Exception:
        return False


def save(uid: str, char_id: str, state: dict[str, Any]) -> bool:
    state["uid"] = str(uid)
    state["char_id"] = str(char_id)
    state["version"] = 1
    state["updated_at"] = time.time()
    actions = state.get("applied_actions")
    if isinstance(actions, dict) and len(actions) > MAX_APPLIED_ACTIONS:
        ordered = sorted(actions.items(), key=lambda item: float((item[1] or {}).get("timestamp") or 0))
        state["applied_actions"] = dict(ordered[-MAX_APPLIED_ACTIONS:])
    return bool(safe_write_json(_path(uid, char_id), state, keep_bak=False))


def append_audit(uid: str, char_id: str, record: dict[str, Any]) -> bool:
    safe = deepcopy(record)
    safe.update({"uid": str(uid), "char_id": str(char_id), "timestamp": time.time()})
    return bool(safe_append_jsonl(get_paths().self_management_audit(uid, char_id=char_id), safe))


def read_audit(uid: str, char_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
    try:
        path = get_paths().self_management_audit(uid, char_id=char_id)
        if not path.exists():
            return []
        rows = []
        for line in path.read_text(encoding="utf-8").splitlines():
            item = json.loads(line)
            if isinstance(item, dict):
                rows.append(item)
        return rows[-max(1, min(int(limit), 200)):]
    except Exception:
        return []
