"""Uid-global persistence for objective health and device observations."""

from __future__ import annotations

import copy
import json
import logging
from pathlib import Path
from threading import Lock, RLock
from typing import Callable

from core.data_paths import DEFAULT_CHAR_ID
from core.memory.path_resolver import resolve_path
from core.memory.scope import MemoryScope
from core.safe_write import safe_write_json

logger = logging.getLogger(__name__)

DEFAULT_HEALTH_STATE = {
    "sleep_segments": [],
    "heart_rate_events": [],
    "phone_sensor_log": [],
    "phone_sensor_today": None,
}

_HEALTH_FIELDS = tuple(DEFAULT_HEALTH_STATE)
_health_locks: dict[str, RLock] = {}
_health_locks_guard = Lock()


def _health_lock(uid: str) -> RLock:
    key = str(uid)
    with _health_locks_guard:
        lock = _health_locks.get(key)
        if lock is None:
            lock = RLock()
            _health_locks[key] = lock
        return lock


def _path(uid: str) -> Path:
    return resolve_path(MemoryScope.global_scope(str(uid)), "health_state")


def _default_state() -> dict:
    return copy.deepcopy(DEFAULT_HEALTH_STATE)


def _normalized_state(raw: object) -> dict:
    state = _default_state()
    if isinstance(raw, dict):
        for field in _HEALTH_FIELDS:
            if field in raw:
                state[field] = copy.deepcopy(raw[field])
    return state


def _has_legacy_data(profile: dict) -> bool:
    return any(profile.get(field) not in (None, [], {}) for field in _HEALTH_FIELDS)


def _active_character_id() -> str | None:
    try:
        from core import pipeline_registry

        pipeline = pipeline_registry.get()
        candidate = getattr(pipeline, "_active_character_id", None)
        return candidate if isinstance(candidate, str) and candidate else None
    except Exception:
        return None


def _legacy_profiles(uid: str) -> list[tuple[str, dict]]:
    """Return populated legacy profiles without constructing any new paths."""
    try:
        from core.sandbox import get_paths
        from core.memory import user_profile

        memory_root = get_paths()._p("runtime", "memory")
        if not memory_root.is_dir():
            return []
        profiles: list[tuple[str, dict]] = []
        for char_dir in sorted(memory_root.iterdir(), key=lambda path: path.name):
            if not char_dir.is_dir() or char_dir.name == "global":
                continue
            profile_path = char_dir / str(uid) / "profile.json"
            if not profile_path.is_file():
                continue
            profile = user_profile.load(uid, char_id=char_dir.name)
            if _has_legacy_data(profile):
                profiles.append((char_dir.name, profile))
        return profiles
    except Exception:
        logger.warning("Unable to inspect legacy health state for uid=%s", uid, exc_info=True)
        return []


def _load_legacy_state(uid: str) -> dict | None:
    profiles = _legacy_profiles(uid)
    if not profiles:
        return None

    active = _active_character_id()
    by_char = dict(profiles)
    selected_char = next(
        (
            candidate
            for candidate in (active, DEFAULT_CHAR_ID)
            if candidate is not None and candidate in by_char
        ),
        profiles[0][0],
    )
    selected = by_char[selected_char]

    variants = {
        json.dumps(
            {field: profile.get(field) for field in _HEALTH_FIELDS},
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        )
        for _, profile in profiles
    }
    if len(variants) > 1:
        logger.warning(
            "Legacy health state conflict for uid=%s across %d character profiles; selected char_id=%s",
            uid,
            len(profiles),
            selected_char,
        )
    return _normalized_state(selected)


def _load_unlocked(uid: str) -> dict:
    path = _path(uid)
    try:
        if path.is_file():
            return _normalized_state(json.loads(path.read_text(encoding="utf-8")))
    except Exception:
        logger.warning("Unable to load health state for uid=%s", uid, exc_info=True)
        return _default_state()

    legacy = _load_legacy_state(uid)
    if legacy is not None:
        # The existence check and first import are serialized by the uid lock.
        if not save(uid, legacy):
            logger.warning("Unable to persist migrated health state for uid=%s", uid)
        return legacy
    return _default_state()


def load(uid: str) -> dict:
    """Load a uid-global health snapshot, lazily importing legacy profile data once."""
    with _health_lock(uid):
        return _load_unlocked(uid)


def save(uid: str, state: dict) -> bool:
    """Atomically save the fields owned by this state, without a character scope."""
    with _health_lock(uid):
        return safe_write_json(_path(uid), _normalized_state(state), keep_bak=False)


def mutate(uid: str, callback: Callable[[dict], None]) -> dict:
    """Reload, modify, and atomically save under one uid-specific lock."""
    with _health_lock(uid):
        state = _load_unlocked(uid)
        callback(state)
        save(uid, state)
        return state
