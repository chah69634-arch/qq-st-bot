"""
Watch 事件接收路由
接收来自可穿戴设备（Apple Watch 等）推送的健康事件，
转发给 scheduler 触发对应的主动消息。

事件格式（POST /watch/event）：
  {"type": "heart_rate", "value": 120}
  {"type": "sleep_end"}
  {"type": "heart_rate", "value": 85}

无需鉴权，由 secret 参数代替（防止公网扫描误触发）。
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query

from admin.auth import verify_token
from core.config_loader import get_config

router = APIRouter()

# 最近一次 Watch 事件快照（内存缓存，重启清零）
_last_watch_data: dict = {}


def _watch_secret() -> str:
    """从 config 读取 watch secret，未配置则返回空字符串（不校验）"""
    return str(get_config().get("scheduler", {}).get("watch_secret", "")).strip()


@router.post("/watch/event", summary="接收 Watch 健康事件")
async def receive_watch_event(
    body: dict,
    secret: str = Query(default=""),
):
    """
    外部设备推送健康事件的入口。

    body 字段：
      type  — 事件类型：heart_rate / sleep_end
      value — 数值（心率时必填）

    若 config.scheduler.watch_secret 已设置，请求必须携带 ?secret=xxx
    """
    expected = _watch_secret()
    if expected and secret != expected:
        raise HTTPException(status_code=401, detail="watch secret 错误")

    event_type = str(body.get("type", "")).strip()
    if not event_type:
        raise HTTPException(status_code=422, detail="缺少 type 字段")

    data = {}
    if event_type == "heart_rate":
        val = body.get("value")
        if val is None:
            raise HTTPException(status_code=422, detail="heart_rate 事件需要 value 字段")
        try:
            data["value"] = int(val)
        except (TypeError, ValueError):
            raise HTTPException(status_code=422, detail="value 必须为整数")
    elif event_type == "sleep_end":
        duration = body.get("duration_seconds")
        if duration:
            try:
                data["duration_minutes"] = round(float(duration) / 60, 1)
            except Exception:
                pass
        data["sleep_start"] = str(body.get("sleep_start", ""))
        data["sleep_end_time"] = str(body.get("sleep_end", ""))

        oid = str(get_config().get("scheduler", {}).get("owner_id", ""))
        if oid:
            from core.memory.user_profile import load as _load, save as _save
            profile = _load(oid)
            profile.setdefault("sleep_segments", [])
            profile["sleep_segments"].append({
                "time": datetime.now().isoformat(),
                "duration_minutes": data.get("duration_minutes", 0),
                "sleep_start": data["sleep_start"],
                "sleep_end_time": data["sleep_end_time"],
            })
            if len(profile["sleep_segments"]) > 20:
                profile["sleep_segments"] = profile["sleep_segments"][-20:]
            _save(oid, profile)
    else:
        raise HTTPException(status_code=422, detail=f"不支持的事件类型: {event_type}")

    # 记录最近事件快照
    _last_watch_data.clear()
    _last_watch_data.update({
        "event_type": event_type,
        "timestamp":  datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        **data,
    })
    _last_watch_data["received_at"] = datetime.now().isoformat()

    from core import scheduler
    import asyncio
    asyncio.create_task(scheduler.on_watch_event(event_type, data))

    return {"message": f"事件 {event_type} 已接收", "data": data}


@router.get("/watch/status", summary="获取最近一次 Watch 事件状态")
async def get_watch_status(auth=Depends(verify_token)):
    """返回最近一次推送的 Watch 事件快照，未收到任何事件时返回空 dict"""
    return _last_watch_data
