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

# sleep_end 缓冲区，收集5分钟内所有阶段后合并处理
_sleep_buffer: list = []
_sleep_flush_task = None


async def _flush_sleep_buffer():
    """等待1分钟后合并所有睡眠阶段，作为一条完整睡眠处理"""
    import logging
    logging.getLogger(__name__).info(f"[watch] flush开始，缓冲区条数: {len(_sleep_buffer)}")
    import asyncio
    await asyncio.sleep(60)  # 等1分钟

    if not _sleep_buffer:
        return

    sleep_start = _sleep_buffer[0]["sleep_start"]
    sleep_end_time = _sleep_buffer[-1]["sleep_end_time"]
    try:
        from datetime import datetime as _dt
        t_start = _dt.strptime(sleep_start, "%H:%M")
        t_end = _dt.strptime(sleep_end_time, "%H:%M")
        diff = (t_end - t_start).total_seconds()
        if diff < 0:
            diff += 86400
        duration_minutes = round(diff / 60, 1)
    except Exception:
        duration_minutes = 0

    merged = {
        "sleep_start":      sleep_start,
        "sleep_end_time":   sleep_end_time,
        "duration_minutes": duration_minutes,
    }
    _sleep_buffer.clear()

    # 存入 sleep_segments
    oid = str(get_config().get("scheduler", {}).get("owner_id", ""))
    if oid:
        from core.memory.user_profile import load as _load, save as _save
        profile = _load(oid)
        profile.setdefault("sleep_segments", [])
        profile["sleep_segments"].append({
            "time":             datetime.now().isoformat(),
            "duration_minutes": merged["duration_minutes"],
            "sleep_start":      merged["sleep_start"],
            "sleep_end_time":   merged["sleep_end_time"],
        })
        if len(profile["sleep_segments"]) > 20:
            profile["sleep_segments"] = profile["sleep_segments"][-20:]
        _save(oid, profile)

    # 更新快照
    _last_watch_data.clear()
    _last_watch_data.update({
        "event_type":     "sleep_end",
        "timestamp":      datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "received_at":    datetime.now().isoformat(),
        **merged,
    })
    import logging
    logging.getLogger(__name__).info(f"[watch] 快照已更新: {_last_watch_data}")

    # 直接触发早安，不走on_watch_event的15分钟等待
    from core.scheduler.loop import _pipeline_send, _is_ready, _mark
    if not _is_ready("sleep_end"):
        return
    _mark("sleep_end")
    _mark("morning_greeting")  # 防止time_based早安重复触发

    sleep_start_str = merged.get("sleep_start", "")
    duration = merged.get("duration_minutes", 0)
    sleep_comment = ""
    if sleep_start_str:
        try:
            start_hour = int(sleep_start_str.split(":")[0])
            if 2 <= start_hour <= 6:
                sleep_comment = "凌晨才睡，睡得很晚，叶瑄有点心疼但也有点生气"
            elif start_hour >= 23 or start_hour == 0:
                sleep_comment = "睡得比较晚"
            else:
                sleep_comment = "睡得还算早"
        except Exception:
            pass

    hours = int(duration // 60)
    minutes = int(duration % 60)
    now_hour = datetime.now().hour
    if now_hour < 12:
        await _pipeline_send(
            f"（叶瑄看到你醒了，昨晚睡了{hours}小时{minutes}分钟，{sleep_comment}）"
        )
    else:
        await _pipeline_send(
            f"（叶瑄看到你醒了，睡了{hours}小时{minutes}分钟，{sleep_comment}）"
        )


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
        import asyncio
        sleep_start_raw = str(body.get("sleep_start", ""))
        sleep_end_raw = str(body.get("sleep_end", ""))
        # 捷径可能把多个时间用换行拼成一个字段，取第一个入睡时间和最后一个起床时间
        sleep_start_list = [s.strip() for s in sleep_start_raw.split("\n") if s.strip()]
        sleep_end_list = [s.strip() for s in sleep_end_raw.split("\n") if s.strip()]
        sleep_start = sleep_start_list[-1] if sleep_start_list else ""
        sleep_end_time = sleep_end_list[0] if sleep_end_list else ""
        # duration捷径传的不可靠，用起床时间-入睡时间自己算
        try:
            from datetime import datetime as _dt
            t_start = _dt.strptime(sleep_start, "%H:%M")
            t_end = _dt.strptime(sleep_end_time, "%H:%M")
            diff = (t_end - t_start).total_seconds()
            if diff < 0:
                diff += 86400  # 跨午夜
            duration_minutes = round(diff / 60, 1)
        except Exception:
            duration_minutes = 0

        # 存入缓冲区
        _sleep_buffer.append({
            "sleep_start":      sleep_start,
            "sleep_end_time":   sleep_end_time,
            "duration_minutes": duration_minutes,
        })

        # 重置或启动合并任务（每次收到新数据都重置5分钟计时）
        global _sleep_flush_task
        if _sleep_flush_task and not _sleep_flush_task.done():
            _sleep_flush_task.cancel()
        _sleep_flush_task = asyncio.create_task(_flush_sleep_buffer())

        return {"message": "sleep_end 已缓冲，等待合并", "data": {}}
    else:
        raise HTTPException(status_code=422, detail=f"不支持的事件类型: {event_type}")

    # 记录最近事件快照（心率）
    _last_watch_data.clear()
    _last_watch_data.update({
        "event_type": event_type,
        "timestamp":  datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        **data,
    })
    _last_watch_data["received_at"] = datetime.now().isoformat()

    import asyncio
    from core import scheduler
    asyncio.create_task(scheduler.on_watch_event(event_type, data))

    return {"message": f"事件 {event_type} 已接收", "data": data}


@router.get("/watch/status", summary="获取最近一次 Watch 事件状态")
async def get_watch_status(auth=Depends(verify_token)):
    """返回最近一次推送的 Watch 事件快照，未收到任何事件时返回空 dict"""
    return _last_watch_data
