"""Admin control surface for durable internal autonomy; requests only inspect/enqueue."""
from __future__ import annotations

import re

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
    return {"uid": uid, "char_id": char_id, "config_enabled": state["config"].get("enabled"), "daily": state.get("daily"), "sources": state.get("sources"), "queued_jobs": [j for j in state.get("jobs", []) if j.get("status") in {"pending", "processing"}], "last_run": (state.get("runs") or [None])[-1], "talk": {"available": talk_mode == "allow" and state["config"].get("talk_enabled"), "mode": talk_mode, "reason": talk_reason, **continuity_status(uid)}}


@router.get("/admin/autonomy/config", summary="读取内置唤醒配置")
async def config(auth=Depends(require_scopes("state.read"))):
    from core.autonomy import store
    uid, char_id = _scope(); return store.load(uid, char_id)["config"]


@router.patch("/admin/autonomy/config", summary="更新内置唤醒配置")
async def patch_config(body: dict, auth=Depends(require_scopes("admin"))):
    from core.autonomy import store
    uid, char_id = _scope(); state = store.load(uid, char_id); cfg = state["config"]
    allowed = {"enabled", "talk_enabled", "daily_evaluation_budget", "min_interval_seconds", "max_steps", "max_tools", "max_write_tools", "total_timeout_seconds", "tool_timeout_seconds"}
    for key in allowed & set(body): cfg[key] = body[key]
    for key in ("daily_evaluation_budget", "min_interval_seconds", "max_steps", "max_tools", "max_write_tools", "total_timeout_seconds", "tool_timeout_seconds"):
        if not isinstance(cfg.get(key), int) or cfg[key] < 0 or cfg[key] > 86400:
            raise HTTPException(status_code=422, detail=f"{key} 非法")
    for name in ("interval", "overflow", "schedule"):
        if name in body:
            if not isinstance(body[name], dict): raise HTTPException(status_code=422, detail=f"{name} 必须为对象")
            cfg[name].update(body[name])
    if not _TIME_RE.match(str(cfg["schedule"].get("time") or "")): raise HTTPException(status_code=422, detail="schedule.time 必须是 HH:MM")
    if int(cfg["interval"].get("seconds") or 0) < 60: raise HTTPException(status_code=422, detail="interval.seconds 至少 60")
    if float(cfg["overflow"].get("threshold") or 0) <= 0: raise HTTPException(status_code=422, detail="overflow.threshold 必须为正数")
    store.save(uid, char_id, state); return cfg


@router.get("/admin/autonomy/runs", summary="读取最近内置唤醒运行")
async def runs(limit: int = 30, auth=Depends(require_scopes("state.read"))):
    from core.autonomy import store
    uid, char_id = _scope(); data = store.load(uid, char_id).get("runs", [])
    return {"runs": list(reversed(data[-max(1, min(limit, 100)):]))}


@router.get("/admin/autonomy/tools", summary="读取自主工具 allowlist")
async def tools(auth=Depends(require_scopes("state.read"))):
    from core.autonomy import store
    from core.tool_dispatcher import _TOOL_REGISTRY, get_tool_effect
    uid, char_id = _scope(); configured = store.load(uid, char_id)["config"].get("tools", {})
    return {"tools": [{"name": name, "source": "MCP" if info.get("category") == "mcp" else "builtin", "effect": get_tool_effect(name) or ("write" if info.get("dangerous") else "read"), "risk": "high" if info.get("dangerous") else "low", "enabled": bool((configured.get(name) or {}).get("enabled")), "idempotent": bool(info.get("mcp_idempotent", False))} for name, info in _TOOL_REGISTRY.items()]}


@router.patch("/admin/autonomy/tools", summary="更新自主工具 allowlist")
async def patch_tools(body: dict, auth=Depends(require_scopes("admin"))):
    from core.autonomy import store
    from core.tool_dispatcher import _TOOL_REGISTRY, get_tool_effect
    uid, char_id = _scope(); name = str(body.get("name") or "")
    if name not in _TOOL_REGISTRY: raise HTTPException(status_code=404, detail="未知工具")
    info = _TOOL_REGISTRY[name]; effect = get_tool_effect(name) or ("write" if info.get("dangerous") else "read")
    if effect not in {"read", "write"} or info.get("dangerous") or info.get("require_confirm"):
        raise HTTPException(status_code=422, detail="该工具不允许 autonomy")
    state = store.load(uid, char_id); state["config"].setdefault("tools", {})[name] = {"enabled": bool(body.get("enabled")), "mcp_explicit": bool(body.get("mcp_explicit", False))}
    store.save(uid, char_id, state); return {"ok": True}


@router.post("/admin/autonomy/test-enqueue", summary="排队一次内置唤醒测试")
async def test_enqueue(body: dict | None = None, auth=Depends(require_scopes("admin"))):
    from core.autonomy import store
    uid, char_id = _scope(); source = str((body or {}).get("source") or "manual")
    if source not in {"manual", "overflow", "schedule", "interval"}: raise HTTPException(status_code=422, detail="无效 source")
    job, status = store.enqueue(uid, char_id, source, dedupe_key=f"manual:{source}:{__import__('uuid').uuid4().hex}")
    return {"status": status, "job_id": job.id if job else ""}
