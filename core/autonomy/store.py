"""Small bounded durable store for autonomy config, jobs, source state and audit runs."""
from __future__ import annotations

import json
import time
from copy import deepcopy

from core.autonomy.models import Job, Run
from core.safe_write import safe_write_json
from core.sandbox import get_paths

MAX_JOBS = 60
MAX_RUNS = 100
LEASE_SECONDS = 90

DEFAULT_CONFIG = {
    "enabled": False,
    "talk_enabled": True,
    "daily_evaluation_budget": 12,
    "min_interval_seconds": 15 * 60,
    "max_steps": 4,
    "max_tools": 4,
    "max_write_tools": 1,
    "total_timeout_seconds": 120,
    "tool_timeout_seconds": 30,
    "schedule": {"enabled": False, "time": "12:00", "weekdays": list(range(7)), "timezone": "local", "window": [], "restart_miss_policy": "skip"},
    "interval": {"enabled": False, "seconds": 6 * 3600},
    "overflow": {"enabled": False, "threshold": 1.6},
    "tools": {},
}


def _path(uid: str, char_id: str):
    return get_paths().autonomy_state(uid, char_id=char_id)


def _default() -> dict:
    return {"config": deepcopy(DEFAULT_CONFIG), "jobs": [], "runs": [], "sources": {}, "daily": {"day": "", "evaluations": 0, "tools": 0, "talks": 0}}


def load(uid: str, char_id: str) -> dict:
    data = _default()
    try:
        path = _path(uid, char_id)
        if path.exists():
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                for key in data:
                    if key in raw and isinstance(raw[key], type(data[key])):
                        data[key] = raw[key]
                if isinstance(raw.get("config"), dict):
                    merged = deepcopy(DEFAULT_CONFIG)
                    merged.update(raw["config"])
                    for section in ("schedule", "interval", "overflow"):
                        if isinstance(raw["config"].get(section), dict):
                            merged[section] = {**DEFAULT_CONFIG[section], **raw["config"][section]}
                    data["config"] = merged
    except Exception:
        # Config/state read failure is fail-safe: no autonomous start is admitted.
        data["config"]["enabled"] = False
    return data


def save(uid: str, char_id: str, state: dict) -> bool:
    state["jobs"] = list(state.get("jobs", []))[-MAX_JOBS:]
    state["runs"] = list(state.get("runs", []))[-MAX_RUNS:]
    path = _path(uid, char_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    return bool(safe_write_json(path, state))


def enqueue(uid: str, char_id: str, source: str, *, dedupe_key: str = "", ttl_seconds: int = 20 * 60) -> tuple[Job | None, str]:
    state = load(uid, char_id)
    now = time.time()
    for raw in state["jobs"]:
        if raw.get("status") in {"pending", "processing"} and raw.get("dedupe_key") and raw.get("dedupe_key") == dedupe_key:
            return None, "duplicate"
    job = Job(uid=str(uid), char_id=str(char_id), source=str(source), dedupe_key=dedupe_key, ttl_seconds=max(60, min(int(ttl_seconds), 3600)))
    state["jobs"].append(job.to_dict())
    save(uid, char_id, state)
    return job, "queued"


def claim_due(uid: str, char_id: str) -> Job | None:
    state = load(uid, char_id)
    now = time.time()
    changed = False
    for raw in state["jobs"]:
        if raw.get("status") == "processing" and float(raw.get("lease_until") or 0) <= now:
            raw["status"] = "pending"; raw["lease_until"] = 0; changed = True
    for raw in state["jobs"]:
        if raw.get("status") != "pending":
            continue
        job = Job.from_dict(raw)
        if now - job.created_at > job.ttl_seconds:
            raw["status"] = "done"; changed = True
            state["runs"].append(Run(uid=uid, char_id=char_id, source=job.source, job_id=job.id, disposition="expired", finished_at=now).to_dict())
            continue
        raw["status"] = "processing"; raw["lease_until"] = now + LEASE_SECONDS; raw["attempts"] = int(raw.get("attempts") or 0) + 1
        save(uid, char_id, state)
        return Job.from_dict(raw)
    if changed:
        save(uid, char_id, state)
    return None


def finish(job: Job, run: Run, *, retry: bool = False) -> None:
    state = load(job.uid, job.char_id)
    for raw in state["jobs"]:
        if raw.get("id") == job.id:
            raw["status"] = "pending" if retry else "done"
            raw["lease_until"] = 0
    state["runs"].append(run.to_dict())
    state.setdefault("sources", {}).setdefault(job.source, {})["last_evaluated_at"] = run.finished_at or time.time()
    _roll_daily(state)
    state["daily"]["evaluations"] += 1
    state["daily"]["tools"] += len(run.tool_names)
    state["daily"]["talks"] += int(run.talk_sent)
    save(job.uid, job.char_id, state)


def _roll_daily(state: dict) -> None:
    from core.scheduler.rhythm import logical_day
    day = logical_day(__import__("datetime").datetime.fromtimestamp(time.time())).isoformat()
    daily = state.setdefault("daily", {})
    if daily.get("day") != day:
        daily.update({"day": day, "evaluations": 0, "tools": 0, "talks": 0})


def source_last_evaluated(state: dict, source: str) -> float:
    return float((state.get("sources", {}).get(source, {}) or {}).get("last_evaluated_at") or 0)
