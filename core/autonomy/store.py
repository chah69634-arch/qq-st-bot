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
    "circuit_failure_threshold": 3,
    "circuit_cooldown_seconds": 3600,
    "schedule": {"enabled": False, "time": "12:00", "weekdays": list(range(7)), "timezone": "local", "window": [], "restart_miss_policy": "skip"},
    "interval": {"enabled": False, "seconds": 6 * 3600},
    "overflow": {"enabled": False, "threshold": 1.6},
    "tools": {},
}


def _path(uid: str, char_id: str):
    return get_paths().autonomy_state(uid, char_id=char_id)


def _default() -> dict:
    return {"config": deepcopy(DEFAULT_CONFIG), "jobs": [], "runs": [], "sources": {}, "daily": {"day": "", "evaluations": 0, "tools": 0, "talks": 0}, "circuit": {"consecutive_failures": 0, "open_until": 0.0}}


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
        if float(raw.get("next_attempt_at") or 0) > now:
            continue
        job = Job.from_dict(raw)
        if now - job.created_at > job.ttl_seconds:
            raw["status"] = "done"; changed = True
            state["runs"].append(Run(uid=uid, char_id=char_id, source=job.source, job_id=job.id, disposition="expired", finished_at=now).to_dict())
            continue
        raw["status"] = "processing"; raw["lease_until"] = now + LEASE_SECONDS; raw["lease_token"] = __import__("uuid").uuid4().hex; raw["attempts"] = int(raw.get("attempts") or 0) + 1
        save(uid, char_id, state)
        return Job.from_dict(raw)
    if changed:
        save(uid, char_id, state)
    return None


def renew(job: Job, *, seconds: int = LEASE_SECONDS) -> bool:
    """Extend only the claim that owns this job; stale workers fail closed."""
    state = load(job.uid, job.char_id)
    for raw in state["jobs"]:
        if raw.get("id") != job.id:
            continue
        if raw.get("status") != "processing" or raw.get("lease_token") != job.lease_token:
            return False
        raw["lease_until"] = time.time() + max(10, int(seconds))
        return save(job.uid, job.char_id, state)
    return False


def finish(job: Job, run: Run, *, retry: bool = False) -> None:
    state = load(job.uid, job.char_id)
    owns_claim = False
    for raw in state["jobs"]:
        if raw.get("id") == job.id:
            if job.lease_token and raw.get("lease_token") != job.lease_token:
                # Another worker reclaimed this job after our lease expired.
                # Preserve its lease/state; retain only the bounded audit run.
                break
            owns_claim = True
            raw["status"] = "pending" if retry else "done"
            raw["lease_until"] = 0
            raw["lease_token"] = ""
            if retry:
                # Bounded exponential retry for temporary guards. It is durable
                # and never turns a denied talk into a tight per-tick loop.
                attempts = max(1, int(raw.get("attempts") or 1))
                raw["next_attempt_at"] = time.time() + min(30 * (2 ** (attempts - 1)), 15 * 60)
            else:
                raw["next_attempt_at"] = 0
    state["runs"].append(run.to_dict())
    if owns_claim:
        evaluated_at = run.finished_at or time.time()
        source_state = state.setdefault("sources", {}).setdefault(job.source, {})
        source_state["last_evaluated_at"] = evaluated_at
        if job.source == "interval" and state["config"].get("interval", {}).get("enabled"):
            source_state["next_due_at"] = evaluated_at + int(state["config"]["interval"].get("seconds") or 0)
        elif job.source == "overflow":
            source_state["next_due_at"] = evaluated_at + int(state["config"].get("min_interval_seconds") or 0)
        roll_daily(state)
        state["daily"]["evaluations"] += 1
        state["daily"]["tools"] += len(run.tool_names)
        state["daily"]["talks"] += int(run.talk_sent)
        circuit = state.setdefault("circuit", {"consecutive_failures": 0, "open_until": 0.0})
        failure = run.disposition in {"tool_failed", "tool_outcome_unknown", "llm_failed", "timeout", "lease_lost"}
        if failure:
            circuit["consecutive_failures"] = int(circuit.get("consecutive_failures") or 0) + 1
            if circuit["consecutive_failures"] >= int(state["config"].get("circuit_failure_threshold") or 3):
                circuit["open_until"] = time.time() + int(state["config"].get("circuit_cooldown_seconds") or 3600)
        elif run.disposition.startswith("completed_") or run.disposition.startswith("talk_"):
            circuit.update({"consecutive_failures": 0, "open_until": 0.0})
    save(job.uid, job.char_id, state)


def roll_daily(state: dict) -> None:
    from core.scheduler.rhythm import logical_day
    day = logical_day(__import__("datetime").datetime.fromtimestamp(time.time())).isoformat()
    daily = state.setdefault("daily", {})
    if daily.get("day") != day:
        daily.update({"day": day, "evaluations": 0, "tools": 0, "talks": 0})


def source_last_evaluated(state: dict, source: str) -> float:
    return float((state.get("sources", {}).get(source, {}) or {}).get("last_evaluated_at") or 0)


def circuit_open(state: dict, *, now: float | None = None) -> bool:
    return float((state.get("circuit") or {}).get("open_until") or 0) > (time.time() if now is None else now)
