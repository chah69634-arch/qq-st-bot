"""Admin control surface for durable internal autonomy; requests only inspect/enqueue."""
from __future__ import annotations

import re
import time
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException

from admin.auth import require_scopes

router = APIRouter()
_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def _scope() -> tuple[str, str]:
    from core.scheduler.loop import _active_char_id_or_none, _owner_id
    uid, char_id = _owner_id(), _active_char_id_or_none()
    if not uid or not char_id:
        raise HTTPException(status_code=409, detail="owner 或当前角色未配置")
    return str(uid), str(char_id)


@router.get("/admin/autonomy/status", summary="读取内置唤醒状态")
async def status(auth=Depends(require_scopes("state.read"))):
    from core.autonomy import store
    from core.autonomy.talk_gate import check
    from core.scheduler.proactive_ledger import continuity_status
    uid, char_id = _scope(); state = store.load(uid, char_id)
    talk_mode, talk_reason = check(uid)
    jobs = [j for j in state.get("jobs", []) if j.get("status") in {"pending", "processing"}]
    current = next((j for j in jobs if j.get("status") == "processing"), None)
    latest = max((float((value or {}).get("last_evaluated_at") or 0) for value in state.get("sources", {}).values()), default=0)
    now = time.time(); cfg = state["config"]
    if current: runtime_state = "运行"
    elif jobs: runtime_state = "排队"
    elif float((state.get("circuit") or {}).get("open_until") or 0) > now: runtime_state = "熔断"
    elif latest and now - latest < int(cfg.get("min_interval_seconds") or 0): runtime_state = "冷却"
    else: runtime_state = "空闲"
    interval = cfg.get("interval") or {}
    next_interval = ((state.get("sources", {}).get("interval", {}) or {}).get("next_due_at") or (store.source_last_evaluated(state, "interval") + int(interval.get("seconds") or 0))) if interval.get("enabled") else None
    return {"uid": uid, "char_id": char_id, "config_enabled": cfg.get("enabled"), "runtime_state": runtime_state, "current_run_id": (current or {}).get("id", ""), "current_stage": (current or {}).get("status", ""), "next_due_at": next_interval, "daily": state.get("daily"), "sources": state.get("sources"), "circuit": state.get("circuit"), "queued_jobs": jobs, "last_run": (state.get("runs") or [None])[-1], "talk": {"available": talk_mode == "allow" and cfg.get("talk_enabled"), "mode": talk_mode, "reason": talk_reason, **continuity_status(uid)}}


@router.get("/admin/autonomy/config", summary="读取内置唤醒配置")
async def config(auth=Depends(require_scopes("state.read"))):
    from core.autonomy import store
    uid, char_id = _scope(); return store.load(uid, char_id)["config"]


@router.patch("/admin/autonomy/config", summary="更新内置唤醒配置")
async def patch_config(body: dict, auth=Depends(require_scopes("admin"))):
    from core.autonomy import store
    uid, char_id = _scope(); state = store.load(uid, char_id); cfg = state["config"]
    bool_fields = {"enabled", "talk_enabled"}
    int_limits = {
        "daily_evaluation_budget": (1, 100), "min_interval_seconds": (0, 86400),
        "max_steps": (1, 8), "max_tools": (0, 8), "max_write_tools": (0, 8),
        "total_timeout_seconds": (1, 600), "tool_timeout_seconds": (1, 120),
        "circuit_failure_threshold": (1, 20), "circuit_cooldown_seconds": (60, 86400),
    }
    for key in bool_fields:
        if key in body:
            if not isinstance(body[key], bool): raise HTTPException(status_code=422, detail=f"{key} 必须为布尔值")
            cfg[key] = body[key]
    for key, (lower, upper) in int_limits.items():
        if key in body:
            value = body[key]
            if isinstance(value, bool) or not isinstance(value, int) or not lower <= value <= upper:
                raise HTTPException(status_code=422, detail=f"{key} 非法")
            cfg[key] = value
    for key in int_limits:
        if not isinstance(cfg.get(key), int) or not int_limits[key][0] <= cfg[key] <= int_limits[key][1]:
            raise HTTPException(status_code=422, detail=f"{key} 非法")
    for name in ("interval", "overflow", "schedule"):
        if name in body:
            if not isinstance(body[name], dict): raise HTTPException(status_code=422, detail=f"{name} 必须为对象")
            cfg[name].update(body[name])
    if not _TIME_RE.match(str(cfg["schedule"].get("time") or "")): raise HTTPException(status_code=422, detail="schedule.time 必须是 HH:MM")
    weekdays = cfg["schedule"].get("weekdays")
    if not isinstance(weekdays, list) or any(isinstance(day, bool) or not isinstance(day, int) or not 0 <= day <= 6 for day in weekdays):
        raise HTTPException(status_code=422, detail="schedule.weekdays 必须是 0-6 的数组")
    timezone = str(cfg["schedule"].get("timezone") or "local")
    if timezone != "local":
        try: ZoneInfo(timezone)
        except Exception as exc: raise HTTPException(status_code=422, detail="schedule.timezone 非法") from exc
    window = cfg["schedule"].get("window") or []
    if window and (not isinstance(window, list) or len(window) != 2 or any(not _TIME_RE.match(str(value)) for value in window)):
        raise HTTPException(status_code=422, detail="schedule.window 必须是两个 HH:MM 时间")
    if cfg["schedule"].get("restart_miss_policy") not in {"skip", "catch_up_once"}:
        raise HTTPException(status_code=422, detail="schedule.restart_miss_policy 非法")
    interval_seconds = cfg["interval"].get("seconds")
    if isinstance(interval_seconds, bool) or not isinstance(interval_seconds, int) or not 60 <= interval_seconds <= 31 * 86400:
        raise HTTPException(status_code=422, detail="interval.seconds 需在 60 秒至 31 天之间")
    threshold = cfg["overflow"].get("threshold")
    if isinstance(threshold, bool) or not isinstance(threshold, (int, float)) or not 0 < float(threshold) <= 10:
        raise HTTPException(status_code=422, detail="overflow.threshold 需在 (0, 10] 内")
    if cfg["max_write_tools"] > cfg["max_tools"]:
        raise HTTPException(status_code=422, detail="max_write_tools 不能超过 max_tools")
    store.save(uid, char_id, state); return cfg


@router.get("/admin/autonomy/runs", summary="读取最近内置唤醒运行")
async def runs(limit: int = 30, auth=Depends(require_scopes("state.read"))):
    from core.autonomy import store
    uid, char_id = _scope(); data = store.load(uid, char_id).get("runs", [])
    return {"runs": list(reversed(data[-max(1, min(limit, 100)):]))}


@router.get("/admin/autonomy/tools", summary="读取自主工具 allowlist")
async def tools(auth=Depends(require_scopes("state.read"))):
    from core.autonomy import store
    from core.autonomy.policy import tool_decisions
    uid, char_id = _scope(); state = store.load(uid, char_id)
    return {"tools": tool_decisions(uid, char_id, state)}


@router.patch("/admin/autonomy/tools", summary="更新自主工具 allowlist")
async def patch_tools(body: dict, auth=Depends(require_scopes("admin"))):
    from core.autonomy import store
    from core.autonomy.policy import tool_eligibility
    from core.tool_dispatcher import _TOOL_REGISTRY, get_tool_effect, is_side_effect_tool
    uid, char_id = _scope(); name = str(body.get("name") or "")
    if name not in _TOOL_REGISTRY: raise HTTPException(status_code=404, detail="未知工具")
    info = _TOOL_REGISTRY[name]; effect = get_tool_effect(name) or ("write" if is_side_effect_tool(name) else "read")
    policy = {"enabled": bool(body.get("enabled")), "mcp_explicit": bool(body.get("mcp_explicit", False)), "outcome_unknown": str(body.get("outcome_unknown") or "fail_closed")}
    eligible, reason = tool_eligibility(name, policy, registry=_TOOL_REGISTRY, effect=effect)
    if policy["enabled"] and not eligible:
        raise HTTPException(status_code=422, detail=f"autonomy tool is not eligible: {reason}")
    if policy["outcome_unknown"] != "fail_closed":
        raise HTTPException(status_code=422, detail="outcome_unknown must be fail_closed")
    if effect not in {"read", "write"} or info.get("dangerous") or info.get("require_confirm"):
        raise HTTPException(status_code=422, detail="该工具不允许 autonomy")
    state = store.load(uid, char_id); state["config"].setdefault("tools", {})[name] = policy
    store.save(uid, char_id, state); return {"ok": True}


@router.post("/admin/autonomy/test-enqueue", summary="排队一次内置唤醒测试")
async def test_enqueue(body: dict | None = None, auth=Depends(require_scopes("admin"))):
    from core.autonomy import store
    uid, char_id = _scope(); source = str((body or {}).get("source") or "manual")
    if source not in {"manual", "overflow", "schedule", "interval"}: raise HTTPException(status_code=422, detail="无效 source")
    job, status = store.enqueue(uid, char_id, source, dedupe_key=f"manual:{source}:{__import__('uuid').uuid4().hex}")
    return {"status": status, "job_id": job.id if job else ""}
