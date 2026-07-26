"""Character-level interests and learning progress (Brief 58)."""
from __future__ import annotations

import json
import math
import time
import uuid
from typing import Iterable

from core.data_paths import DEFAULT_CHAR_ID
from core.safe_write import safe_write_json

MAX_ACTIVE_INTERESTS = 3
RECENT_SCORE_LIMIT = 5
STALL_SESSION_COUNT = 4
PAUSE_AFTER_DAYS = 30
RETIRE_AFTER_DAYS = 90
VALID_DOMAINS = frozenset({"writing", "music", "drawing", "other"})
VALID_ORIGINS = frozenset({"topic_stats", "user_pref_mirror", "trait_underrepresented"})
# Brief 58 once mirrored a full user preference into a character interest.  Those
# entries have no character-owned, actionable skill name and must not drive
# practice, prompt context, or ambient presence.  Keep the old origin readable
# so the original record can be audited, but retire it during normalization.
RETIRED_ORIGINS = frozenset({"user_pref_mirror"})


def _path(char_id: str):
    from core.sandbox import get_paths
    return get_paths().interest_state(char_id=char_id)


def _default() -> dict:
    return {"interests": []}


def _normalise(raw: object) -> dict:
    if not isinstance(raw, dict) or not isinstance(raw.get("interests", []), list):
        return _default()
    interests = []
    for item in raw.get("interests", []):
        if not isinstance(item, dict) or not item.get("id") or not item.get("name"):
            continue
        entry = dict(item)
        entry["domain"] = entry.get("domain") if entry.get("domain") in VALID_DOMAINS else "other"
        entry["origin"] = entry.get("origin") if entry.get("origin") in VALID_ORIGINS else "topic_stats"
        entry["status"] = entry.get("status") if entry.get("status") in {"active", "paused", "retired"} else "active"
        if entry["origin"] in RETIRED_ORIGINS:
            entry["status"] = "retired"
        entry["level"] = min(5, max(1, int(entry.get("level", 1) or 1)))
        entry["recent_scores"] = [float(v) for v in entry.get("recent_scores", []) if isinstance(v, (int, float))][-RECENT_SCORE_LIMIT:]
        entry["learning_progress"] = learning_progress(entry["recent_scores"])
        entry.setdefault("created_at", time.time())
        entry.setdefault("stalled_since", None)
        interests.append(entry)
    return {"interests": interests}


def load(char_id: str = DEFAULT_CHAR_ID) -> dict:
    path = _path(char_id)
    if not path.exists():
        return _default()
    try:
        return _normalise(json.loads(path.read_text(encoding="utf-8")))
    except Exception:
        return _default()


def learning_progress(scores: Iterable[float]) -> float:
    values = [float(v) for v in scores]
    n = len(values)
    if n < 2:
        return 0.0
    x_mean = (n - 1) / 2
    y_mean = sum(values) / n
    denom = sum((i - x_mean) ** 2 for i in range(n))
    if not denom:
        return 0.0
    return sum((i - x_mean) * (v - y_mean) for i, v in enumerate(values)) / denom


def active_interests(char_id: str = DEFAULT_CHAR_ID) -> list[dict]:
    return [x for x in load(char_id)["interests"] if x["status"] == "active"]


def highest_level_for_domain(char_id: str, domain: str) -> int | None:
    levels = [x["level"] for x in active_interests(char_id) if x.get("domain") == domain]
    return max(levels) if levels else None


async def add_interest(name: str, domain: str, origin: str, *, char_id: str = DEFAULT_CHAR_ID, rationale: str = "", uid: str = "") -> dict | None:
    from core.memory.locks import global_lock
    async with global_lock("interest_state"):
        state = load(char_id)
        if sum(x.get("status") == "active" for x in state["interests"]) >= MAX_ACTIVE_INTERESTS:
            return None
        if any(x.get("name", "").casefold() == name.strip().casefold() and x.get("status") != "retired" for x in state["interests"]):
            return None
        entry = {
            "id": f"int_{uuid.uuid4().hex[:12]}", "name": name.strip(),
            "domain": domain if domain in VALID_DOMAINS else "other",
            "origin": origin if origin in VALID_ORIGINS else "topic_stats",
            "created_at": time.time(), "level": 1, "status": "active",
            "recent_scores": [], "learning_progress": 0.0, "stalled_since": None,
        }
        state["interests"].append(entry)
        path = _path(char_id); path.parent.mkdir(parents=True, exist_ok=True)
        safe_write_json(path, state)
    _provenance(uid, char_id, entry["id"], "", entry["name"], "interest_seeded")
    return entry


async def record_score(interest_id: str, score: float, *, char_id: str = DEFAULT_CHAR_ID, uid: str = "") -> dict | None:
    from core.memory.locks import global_lock
    async with global_lock("interest_state"):
        state = load(char_id)
        item = next((x for x in state["interests"] if x["id"] == interest_id), None)
        if item is None:
            return None
        previous = list(item["recent_scores"])
        item["recent_scores"] = (previous + [float(score)])[-RECENT_SCORE_LIMIT:]
        item["learning_progress"] = learning_progress(item["recent_scores"])
        recent = item["recent_scores"][-STALL_SESSION_COUNT:]
        if len(recent) == STALL_SESSION_COUNT and max(recent) <= recent[0]:
            item["stalled_since"] = item.get("stalled_since") or time.time()
        elif len(recent) >= 2 and recent[-1] > min(recent[:-1]):
            item["stalled_since"] = None
        path = _path(char_id); path.parent.mkdir(parents=True, exist_ok=True)
        safe_write_json(path, state)
        return dict(item)


async def set_level(interest_id: str, level: int, *, char_id: str = DEFAULT_CHAR_ID, uid: str = "") -> tuple[dict | None, int]:
    from core.memory.locks import global_lock
    async with global_lock("interest_state"):
        state = load(char_id); item = next((x for x in state["interests"] if x["id"] == interest_id), None)
        if item is None: return None, 0
        old = int(item["level"]); item["level"] = min(5, max(old, int(level)))
        path = _path(char_id); path.parent.mkdir(parents=True, exist_ok=True); safe_write_json(path, state)
    if item["level"] > old: _provenance(uid, char_id, interest_id, str(old), str(item["level"]), "level_up")
    return dict(item), old


async def apply_lifecycle(*, char_id: str = DEFAULT_CHAR_ID, uid: str = "", now: float | None = None) -> list[tuple[str, str, str]]:
    from core.memory.locks import global_lock
    now = time.time() if now is None else now; changes = []
    async with global_lock("interest_state"):
        state = load(char_id)
        for item in state["interests"]:
            stalled = item.get("stalled_since")
            if not isinstance(stalled, (int, float)): continue
            age_days = (now - stalled) / 86400
            old = item["status"]
            if old == "active" and age_days >= PAUSE_AFTER_DAYS: item["status"] = "paused"
            elif old == "paused" and age_days >= PAUSE_AFTER_DAYS + RETIRE_AFTER_DAYS: item["status"] = "retired"
            if item["status"] != old: changes.append((item["id"], old, item["status"]))
        if changes:
            path = _path(char_id); path.parent.mkdir(parents=True, exist_ok=True); safe_write_json(path, state)
    for iid, old, new in changes: _provenance(uid, char_id, iid, old, new, f"interest_{new}")
    return changes


def _provenance(uid: str, char_id: str, field: str, before: str, after: str, signal: str) -> None:
    try:
        from core.memory import provenance_log
        provenance_log.append(str(uid or "system"), char_id, artifact="interest_state", field=field, before_gist=before, after_gist=after, trigger_signal=signal, origin={"source": "scheduler"})
    except Exception:
        pass
