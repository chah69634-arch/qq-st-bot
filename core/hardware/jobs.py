"""Persistent background jobs for long-running hardware actions.

The tool call only validates and records a job. Device I/O and timing live in
the worker so a long vibration never occupies the conversation/tool-loop turn.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import time
from contextlib import suppress
from uuid import uuid4

from core.safe_write import safe_write_json
from core.sandbox import get_paths


logger = logging.getLogger(__name__)

ACTIVE_STATUSES = frozenset({"accepted", "started"})
TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled", "expired"})
MAX_JOB_HISTORY = 100
DEFAULT_MAX_DURATION_MS = 900_000

_jobs: dict[str, dict] = {}
_tasks: dict[str, asyncio.Task] = {}
_started = False
_loaded = False
_loaded_path_token = ""
_state_lock: asyncio.Lock | None = None
_disconnect_listener = None


class HardwareJobError(RuntimeError):
    """Base error for a job that cannot be accepted."""


class HardwareJobConflict(HardwareJobError):
    def __init__(self, existing_job_id: str):
        self.existing_job_id = existing_job_id
        super().__init__(f"hardware job already active: {existing_job_id}")


def _now() -> float:
    return time.time()


def _state_path():
    return get_paths().hardware_jobs()


def _lock() -> asyncio.Lock:
    global _state_lock
    if _state_lock is None:
        _state_lock = asyncio.Lock()
    return _state_lock


def _ensure_loaded() -> None:
    global _loaded, _loaded_path_token
    path_token = str(_state_path())
    if _loaded and _loaded_path_token == path_token:
        return
    _jobs.clear()
    path = _state_path()
    candidates = [path, path.with_suffix(path.suffix + ".bak")]
    for candidate in candidates:
        if not candidate.exists():
            continue
        try:
            payload = json.loads(candidate.read_text(encoding="utf-8"))
            raw_jobs = payload.get("jobs", []) if isinstance(payload, dict) else []
            if isinstance(raw_jobs, list):
                for raw in raw_jobs:
                    if not isinstance(raw, dict) or not raw.get("job_id"):
                        continue
                    job = _normalise_job(raw)
                    _jobs[job["job_id"]] = job
            break
        except Exception as exc:
            logger.warning("[hardware_jobs] state load failed path=%s: %s", candidate, exc)
    _loaded = True
    _loaded_path_token = path_token


def _normalise_job(raw: dict) -> dict:
    job = dict(raw)
    job.setdefault("status", "failed")
    job.setdefault("kind", "vibration")
    job.setdefault("device_index", None)
    job.setdefault("requested_device_index", job.get("device_index"))
    job.setdefault("intensity", 0.5)
    job.setdefault("pattern_name", "")
    job.setdefault("steps", [])
    job.setdefault("duration_ms", 0)
    job.setdefault("accepted_at", None)
    job.setdefault("started_at", None)
    job.setdefault("deadline_at", None)
    job.setdefault("ended_at", None)
    job.setdefault("error", None)
    job.setdefault("outcome", None)
    job.setdefault("stop_confirmed", None)
    return job


def _persist_locked() -> bool:
    ordered = sorted(_jobs.values(), key=lambda item: float(item.get("accepted_at") or 0), reverse=True)
    return safe_write_json(_state_path(), {"schema_version": 1, "jobs": ordered[:MAX_JOB_HISTORY]})


def _max_duration_ms() -> int:
    try:
        from core.config_loader import get_config

        value = get_config().get("hardware", {}).get("max_job_duration_ms", DEFAULT_MAX_DURATION_MS)
        return max(1, min(3_600_000, int(value)))
    except Exception:
        return DEFAULT_MAX_DURATION_MS


def _normalise_intensity(value: float) -> float:
    try:
        value = float(value)
    except (TypeError, ValueError):
        raise HardwareJobError("invalid intensity") from None
    if not math.isfinite(value):
        raise HardwareJobError("invalid intensity")
    return min(1.0, max(0.0, value))


def _normalise_duration(value: int) -> int:
    try:
        duration = int(value)
    except (TypeError, ValueError):
        raise HardwareJobError("invalid duration") from None
    return min(_max_duration_ms(), max(0, duration))


def _normalise_steps(steps: list[tuple[float, int]] | None) -> list[list[float | int]]:
    if not steps:
        steps = [(0.5, 500)]
    normalised: list[list[float | int]] = []
    remaining = _max_duration_ms()
    for intensity, duration_ms in list(steps)[:32]:
        step_duration = min(_normalise_duration(duration_ms), remaining)
        normalised.append([_normalise_intensity(intensity), step_duration])
        remaining -= step_duration
        if remaining <= 0:
            break
    return normalised or [[0.5, 500]]


def _job_duration_ms(job: dict) -> int:
    if job.get("kind") == "pattern":
        return sum(int(step[1]) for step in job.get("steps", []))
    return int(job.get("duration_ms") or 0)


def _conflicts(job: dict, existing: dict) -> bool:
    if existing.get("status") not in ACTIVE_STATUSES:
        return False
    requested = job.get("requested_device_index")
    current = existing.get("requested_device_index")
    return requested is None or current is None or int(requested) == int(current)


def _public(job: dict) -> dict:
    result = dict(job)
    now = _now()
    status = result.get("status")
    if status == "started" and result.get("deadline_at"):
        remaining = max(0.0, float(result["deadline_at"]) - now)
    elif status == "accepted":
        remaining = max(0.0, _job_duration_ms(result) / 1000.0)
    else:
        remaining = 0.0
    result["remaining_seconds"] = round(remaining, 3)
    result["remaining_ms"] = int(round(remaining * 1000))
    result["start_time"] = result.get("started_at")
    result["end_time"] = result.get("ended_at")
    return result


def _format_remaining(seconds: float) -> str:
    if seconds >= 60:
        return f"约 {max(1, math.ceil(seconds / 60))} 分钟"
    return f"约 {max(1, math.ceil(seconds))} 秒"


def format_prompt() -> str:
    """Return a system-computed prompt fragment for active jobs only."""
    _ensure_loaded()
    lines: list[str] = []
    for job in sorted(_jobs.values(), key=lambda item: float(item.get("accepted_at") or 0)):
        if job.get("status") == "accepted":
            lines.append(
                f"硬件动作已受理（任务 {job['job_id'][:8]}），正在等待设备确认启动；"
                f"预计持续 {_format_remaining(_job_duration_ms(job) / 1000.0)}。"
            )
        elif job.get("status") == "started":
            remaining = _public(job)["remaining_seconds"]
            lines.append(
                f"刚才的硬件动作仍在运行（任务 {job['job_id'][:8]}），还剩 {_format_remaining(remaining)}；"
                "不要把它说成已经完成，设备状态以系统记录为准。"
            )
    if not lines:
        return ""
    return "<当前硬件动作状态>\n" + "\n".join(lines) + "\n</当前硬件动作状态>"


def list_jobs(*, status: str | None = None, active_only: bool = False) -> list[dict]:
    _ensure_loaded()
    values = list(_jobs.values())
    if active_only:
        values = [job for job in values if job.get("status") in ACTIVE_STATUSES]
    if status:
        values = [job for job in values if job.get("status") == status]
    return [_public(job) for job in sorted(values, key=lambda item: float(item.get("accepted_at") or 0), reverse=True)]


def get_job(job_id: str) -> dict | None:
    _ensure_loaded()
    job = _jobs.get(str(job_id))
    return _public(job) if job else None


async def _mark_started(job_id: str, actual_device_index: int) -> None:
    async with _lock():
        job = _jobs.get(job_id)
        if not job or job.get("status") != "accepted":
            return
        started_at = _now()
        job["status"] = "started"
        job["device_index"] = actual_device_index
        job["started_at"] = started_at
        job["deadline_at"] = started_at + (_job_duration_ms(job) / 1000.0)
        job["updated_at"] = started_at
        _persist_locked()


async def _finish(job_id: str, status: str, *, error: str | None = None, outcome: str | None = None, stop_confirmed: bool | None = None) -> None:
    if status not in TERMINAL_STATUSES:
        raise ValueError(f"invalid terminal status: {status}")
    async with _lock():
        job = _jobs.get(job_id)
        if not job or job.get("status") in TERMINAL_STATUSES:
            return
        job["status"] = status
        job["ended_at"] = _now()
        job["updated_at"] = job["ended_at"]
        if error is not None:
            job["error"] = error
        if outcome is not None:
            job["outcome"] = outcome
        if stop_confirmed is not None:
            job["stop_confirmed"] = stop_confirmed
        _persist_locked()


async def _start_command(device_index: int | None, intensity: float) -> int | None:
    from core.hardware import buttplug_client

    return await buttplug_client._start_vibration_command(device_index, intensity)


async def _stop_command(device_index: int | None) -> bool:
    from core.hardware import buttplug_client

    return await buttplug_client._stop_device_command(device_index)


async def _run_job(job_id: str) -> None:
    job = _jobs.get(job_id)
    if not job:
        return
    requested_index = job.get("requested_device_index")
    actual_index = job.get("device_index") if job.get("device_index") is not None else requested_index
    command_attempted = False
    try:
        if job.get("kind") == "pattern":
            for intensity, duration_ms in job.get("steps") or [[0.5, 500]]:
                command_attempted = True
                actual_index = await _start_command(actual_index, float(intensity))
                if actual_index is None:
                    raise ConnectionError("device unavailable")
                if job.get("status") == "accepted":
                    await _mark_started(job_id, actual_index)
                await asyncio.sleep(int(duration_ms) / 1000.0)
        else:
            command_attempted = True
            actual_index = await _start_command(actual_index, float(job.get("intensity", 0.5)))
            if actual_index is None:
                raise ConnectionError("device unavailable")
            await _mark_started(job_id, actual_index)
            await asyncio.sleep(int(job.get("duration_ms") or 0) / 1000.0)

        stop_confirmed = await _stop_command(actual_index)
        if stop_confirmed:
            await _finish(job_id, "completed", outcome="completed", stop_confirmed=True)
        else:
            await _finish(job_id, "failed", error="设备停止未确认，动作结果不明", outcome="unknown", stop_confirmed=False)
    except asyncio.CancelledError:
        current = get_job(job_id)
        if current and current.get("status") in TERMINAL_STATUSES:
            return
        stop_confirmed = False
        if command_attempted:
            with suppress(Exception):
                stop_confirmed = await _stop_command(actual_index)
        if stop_confirmed:
            await _finish(job_id, "cancelled", outcome="cancelled", stop_confirmed=True)
        else:
            await _finish(job_id, "failed", error="取消时未能确认设备停止，动作结果不明", outcome="unknown", stop_confirmed=False)
    except Exception as exc:
        stop_confirmed = False
        if command_attempted:
            with suppress(Exception):
                stop_confirmed = await _stop_command(actual_index)
        await _finish(job_id, "failed", error=str(exc)[:240] or "硬件动作失败", outcome="failed" if stop_confirmed else "unknown", stop_confirmed=stop_confirmed)
    finally:
        _tasks.pop(job_id, None)


async def _accept(job: dict) -> tuple[dict, bool]:
    await startup()
    async with _lock():
        for existing in _jobs.values():
            if _conflicts(job, existing):
                same_request = (
                    existing.get("kind") == job.get("kind")
                    and existing.get("requested_device_index") == job.get("requested_device_index")
                    and existing.get("intensity") == job.get("intensity")
                    and existing.get("pattern_name") == job.get("pattern_name")
                    and _job_duration_ms(existing) == _job_duration_ms(job)
                )
                if same_request:
                    return _public(existing), True
                raise HardwareJobConflict(existing["job_id"])
        job["accepted_at"] = _now()
        job["updated_at"] = job["accepted_at"]
        _jobs[job["job_id"]] = job
        if not _persist_locked():
            _jobs.pop(job["job_id"], None)
            raise HardwareJobError("hardware job state could not be persisted")
        _tasks[job["job_id"]] = asyncio.create_task(_run_job(job["job_id"]), name=f"hardware-job:{job['job_id'][:8]}")
        return _public(job), False


async def submit_vibration(*, intensity: float = 0.5, duration_ms: int = 1000, device_index: int | None = None) -> tuple[dict, bool]:
    return await _accept({
        "job_id": uuid4().hex,
        "kind": "vibration",
        "status": "accepted",
        "requested_device_index": device_index,
        "device_index": None,
        "intensity": _normalise_intensity(intensity),
        "duration_ms": _normalise_duration(duration_ms),
        "pattern_name": "",
        "steps": [],
        "accepted_at": None,
        "started_at": None,
        "deadline_at": None,
        "ended_at": None,
        "error": None,
        "outcome": None,
        "stop_confirmed": None,
    })


async def submit_pattern(*, pattern_name: str, steps: list[tuple[float, int]], device_index: int | None = None) -> tuple[dict, bool]:
    normalised = _normalise_steps(steps)
    return await _accept({
        "job_id": uuid4().hex,
        "kind": "pattern",
        "status": "accepted",
        "requested_device_index": device_index,
        "device_index": None,
        "intensity": None,
        "duration_ms": sum(int(step[1]) for step in normalised),
        "pattern_name": pattern_name,
        "steps": normalised,
        "accepted_at": None,
        "started_at": None,
        "deadline_at": None,
        "ended_at": None,
        "error": None,
        "outcome": None,
        "stop_confirmed": None,
    })


async def cancel_job(job_id: str, *, reason: str = "explicit") -> dict | None:
    _ensure_loaded()
    task = None
    async with _lock():
        job = _jobs.get(str(job_id))
        if job is None:
            return None
        if job.get("status") in TERMINAL_STATUSES:
            return _public(job)
        task = _tasks.get(str(job_id))
        job["cancel_reason"] = reason
        if task is not None and task is not asyncio.current_task():
            task.cancel()
    if task is not None and task is not asyncio.current_task():
        with suppress(asyncio.CancelledError):
            await task
    current = get_job(str(job_id))
    if current and current.get("status") in ACTIVE_STATUSES:
        stop_confirmed = False
        with suppress(Exception):
            stop_confirmed = await _stop_command(current.get("device_index"))
        await _finish(str(job_id), "cancelled" if stop_confirmed else "failed", error=None if stop_confirmed else "取消时未能确认设备停止，动作结果不明", outcome="cancelled" if stop_confirmed else "unknown", stop_confirmed=stop_confirmed)
    return get_job(str(job_id))


async def cancel_active(*, device_index: int | None = None, job_id: str | None = None, reason: str = "explicit") -> list[dict]:
    _ensure_loaded()
    if job_id is not None:
        result = await cancel_job(job_id, reason=reason)
        return [result] if result else []
    active = [job["job_id"] for job in list(_jobs.values()) if job.get("status") in ACTIVE_STATUSES and (device_index is None or job.get("device_index") in (None, device_index))]
    results = []
    for current_id in active:
        result = await cancel_job(current_id, reason=reason)
        if result:
            results.append(result)
    return results


async def handle_device_lost(device_index: int | None = None) -> None:
    _ensure_loaded()
    affected: list[tuple[str, asyncio.Task | None]] = []
    async with _lock():
        now = _now()
        for job in _jobs.values():
            if job.get("status") not in ACTIVE_STATUSES:
                continue
            if device_index is not None and job.get("device_index") not in (None, device_index):
                continue
            job.update({"status": "failed", "ended_at": now, "updated_at": now, "error": "设备连接已断开，动作结果不明", "outcome": "unknown", "stop_confirmed": False})
            affected.append((job["job_id"], _tasks.get(job["job_id"])))
        if affected:
            _persist_locked()
    for _, task in affected:
        if task is not None and task is not asyncio.current_task():
            task.cancel()
    await asyncio.gather(*(task for _, task in affected if task is not None and task is not asyncio.current_task()), return_exceptions=True)


async def startup() -> None:
    """Load state and recover actions left active by a previous process."""
    global _started, _disconnect_listener
    _ensure_loaded()
    if _started:
        return
    stale: list[dict] = []
    async with _lock():
        if _started:
            return
        _started = True
        now = _now()
        for job in _jobs.values():
            if job.get("status") not in ACTIVE_STATUSES:
                continue
            job.update({"status": "expired", "ended_at": now, "updated_at": now, "error": "进程重启，未恢复旧硬件动作", "outcome": "unknown", "stop_confirmed": False})
            stale.append(dict(job))
        if stale:
            _persist_locked()

    from core.hardware import buttplug_client

    async def _on_disconnect(device_index: int | None = None):
        await handle_device_lost(device_index)

    _disconnect_listener = _on_disconnect
    buttplug_client.add_disconnect_listener(_disconnect_listener)
    for job in stale:
        stop_confirmed = False
        with suppress(Exception):
            stop_confirmed = await _stop_command(job.get("device_index"))
        async with _lock():
            current = _jobs.get(job["job_id"])
            if current is not None:
                current["stop_confirmed"] = bool(stop_confirmed)
                current["outcome"] = "expired" if stop_confirmed else "unknown"
                if not stop_confirmed:
                    current["error"] = "重启恢复未能确认设备停止，动作结果不明"
                _persist_locked()


async def shutdown(*, timeout: float = 5.0) -> None:
    """Cancel active workers, confirm stop where possible, then unregister callbacks."""
    global _started, _disconnect_listener, _state_lock
    _ensure_loaded()
    active_ids = [job["job_id"] for job in _jobs.values() if job.get("status") in ACTIVE_STATUSES]
    if active_ids:
        try:
            await asyncio.wait_for(asyncio.gather(*(cancel_job(job_id, reason="shutdown") for job_id in active_ids)), timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning("[hardware_jobs] shutdown cleanup timed out; marking remaining jobs unknown")
            for task in tuple(_tasks.values()):
                if not task.done():
                    task.cancel()
            async with _lock():
                now = _now()
                changed = False
                for job in _jobs.values():
                    if job.get("status") not in ACTIVE_STATUSES:
                        continue
                    job.update({"status": "failed", "ended_at": now, "updated_at": now, "error": "进程关闭时未能确认设备停止", "outcome": "unknown", "stop_confirmed": False})
                    changed = True
                if changed:
                    _persist_locked()
    from core.hardware import buttplug_client

    if _disconnect_listener is not None:
        buttplug_client.remove_disconnect_listener(_disconnect_listener)
    _disconnect_listener = None
    _started = False
    _state_lock = None


async def _reset_for_tests() -> None:
    global _started, _loaded, _loaded_path_token, _disconnect_listener, _state_lock
    with suppress(Exception):
        await shutdown(timeout=1.0)
    from core.hardware import buttplug_client

    if _disconnect_listener is not None:
        buttplug_client.remove_disconnect_listener(_disconnect_listener)
    _jobs.clear()
    _tasks.clear()
    _started = False
    _loaded = False
    _loaded_path_token = ""
    _disconnect_listener = None
    _state_lock = None
