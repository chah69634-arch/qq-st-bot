"""phone_control 任务 session 状态：步数上限 + 超时，独立于设备自己数步。

设备是不可信输入源（可能有 bug、可能被篡改），步数和超时判定必须由后端自己维护，不能只信
设备上报的 `step` 字段——那个字段只用来做请求去重/日志关联，不作为限流依据。
"""
from __future__ import annotations

import json
import logging
import time

from core.safe_write import safe_write_json

logger = logging.getLogger(__name__)

MAX_STEPS = 20
STEP_TIMEOUT_SECONDS = 180  # 单步（含视觉模型调用）超时
TASK_MAX_AGE_SECONDS = 30 * 60  # 超过这个时间没有新 step，任务视为已死，清理掉
HISTORY_MAX_ENTRIES = 6  # 只喂给视觉模型最近几步的摘要，不是完整轨迹——省 token，也避免旧误判反复影响新判断
_ACTIVE = "active"
_TERMINAL_STATUSES = frozenset({"done", "need_confirmation", "refused", "cancelled"})


def _load() -> dict:
    from core.sandbox import get_paths

    f = get_paths().phone_control_tasks()
    if not f.exists():
        return {}
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        logger.warning("[phone_control.task_state] 读取任务状态失败，重置")
        return {}


def _save(data: dict) -> None:
    from core.sandbox import get_paths

    now = time.time()
    pruned = {
        task_id: entry
        for task_id, entry in data.items()
        if isinstance(entry, dict)
        and now - float(entry.get("last_step_at", 0)) < TASK_MAX_AGE_SECONDS
    }
    safe_write_json(get_paths().phone_control_tasks(), pruned)


def start_task(task_id: str, user_id: str, task_description: str) -> None:
    data = _load()
    now = time.time()
    data[task_id] = {
        "user_id": str(user_id),
        "task": task_description,
        "status": _ACTIVE,
        "step": 0,
        "created_at": now,
        "last_step_at": now,
        "history": [],
    }
    _save(data)


def append_history(task_id: str, step: int, action_type: str, reasoning: str) -> None:
    data = _load()
    entry = data.get(task_id)
    if not isinstance(entry, dict):
        return
    history = entry.get("history")
    if not isinstance(history, list):
        history = []
    history.append({"step": step, "action_type": action_type, "reasoning": reasoning[:120]})
    entry["history"] = history[-HISTORY_MAX_ENTRIES:]
    data[task_id] = entry
    _save(data)


def get_history_summary(task_id: str) -> str:
    data = _load()
    entry = data.get(task_id)
    if not isinstance(entry, dict):
        return ""
    history = entry.get("history")
    if not isinstance(history, list) or not history:
        return ""
    return "\n".join(
        f"第{item.get('step')}步：{item.get('action_type')}——{item.get('reasoning')}"
        for item in history
        if isinstance(item, dict)
    )


def record_step(task_id: str) -> tuple[int | None, str | None]:
    """推进一步。返回 (新 step 数, refuse 原因)。

    task_id 不存在（从没 start_task 过，或者已经被判定为死任务清理掉了）时返回 (None, "unknown_task")。
    超过 MAX_STEPS 或距上一步超过 STEP_TIMEOUT_SECONDS 时返回 refuse 原因，
    同时把任务标记为 refused（幂等——重复调用不会重复计数超限）。
    """
    data = _load()
    entry = data.get(task_id)
    if not isinstance(entry, dict):
        return None, "unknown_task"
    if entry.get("status") in _TERMINAL_STATUSES:
        return None, f"task_already_{entry.get('status')}"

    now = time.time()
    last_step_at = float(entry.get("last_step_at", now))
    if now - last_step_at > STEP_TIMEOUT_SECONDS:
        entry["status"] = "refused"
        data[task_id] = entry
        _save(data)
        return None, "step_timeout"

    step = int(entry.get("step", 0)) + 1
    if step > MAX_STEPS:
        entry["status"] = "refused"
        data[task_id] = entry
        _save(data)
        return None, "max_steps_exceeded"

    entry["step"] = step
    entry["last_step_at"] = now
    data[task_id] = entry
    _save(data)
    return step, None


def get_task(task_id: str) -> dict | None:
    data = _load()
    entry = data.get(task_id)
    return entry if isinstance(entry, dict) else None


def mark_status(task_id: str, status: str) -> None:
    if status not in _TERMINAL_STATUSES:
        raise ValueError(f"not a terminal status: {status}")
    data = _load()
    entry = data.get(task_id)
    if not isinstance(entry, dict):
        return
    entry["status"] = status
    entry["last_step_at"] = time.time()
    data[task_id] = entry
    _save(data)
