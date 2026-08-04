"""Volatile per-group transition reservations for Dream Stage."""
from __future__ import annotations

import asyncio
from collections import defaultdict
from uuid import uuid4

_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
_entering: dict[str, str] = {}


def lock_for(group_id: str) -> asyncio.Lock:
    return _locks[group_id]


def reserve_enter(group_id: str) -> str | None:
    if group_id in _entering:
        return None
    token = uuid4().hex
    _entering[group_id] = token
    return token


def is_entering(group_id: str) -> bool:
    return group_id in _entering


def owns_enter(group_id: str, token: str) -> bool:
    return _entering.get(group_id) == token


def release_enter(group_id: str, token: str | None = None) -> None:
    if token is None or _entering.get(group_id) == token:
        _entering.pop(group_id, None)
