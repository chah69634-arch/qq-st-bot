import asyncio
import logging

from core.scheduler.loop import _is_ready, _mark, _owner_id, _pipeline_send, _cfg

logger = logging.getLogger(__name__)


async def on_watch_event(event_type: str, data: dict):
    """
    接收 Watch 事件并触发主动行为。

    event_type:
        "heart_rate"  — data = {"value": int}
        "sleep_end"   — data = {"duration_minutes": float, "sleep_start": str, ...}
    """
    cfg = _cfg()
    if not cfg.get("enabled", True):
        return
    if not _owner_id():
        return

    if event_type == "heart_rate":
        hr = int(data.get("value", 0))
        now_hour = __import__("datetime").datetime.now().hour

        # 06-08点跳过，可能晨跑
        if 6 <= now_hour < 8:
            logger.info(f"[scheduler] 心率数据在晨跑时段，跳过触发 hr={hr}")
            return

        # 深夜(22-06点)降低阈值，>100就关心
        in_night = now_hour >= 22 or now_hour < 6
        if in_night:
            if hr > 120 and _is_ready("hr_critical"):
                await _pipeline_send(f"（深夜，叶瑄看到你的心率{hr}）")
                _mark("hr_critical")
                logger.info(f"[scheduler] 深夜心率危急触发 hr={hr}")
            elif hr > 100 and _is_ready("hr_high"):
                await _pipeline_send(f"（深夜，叶瑄注意到你的心率{hr}）")
                _mark("hr_high")
                logger.info(f"[scheduler] 深夜心率偏高触发 hr={hr}")
        else:
            if hr > 120 and _is_ready("hr_critical"):
                await _pipeline_send(f"（叶瑄看到你的心率{hr}，皱了皱眉）")
                _mark("hr_critical")
                logger.info(f"[scheduler] 心率危急触发 hr={hr}")
            elif hr > 100 and _is_ready("hr_high"):
                await _pipeline_send(f"（叶瑄看到你的心率有点高，{hr}）")
                _mark("hr_high")
                logger.info(f"[scheduler] 心率偏高触发 hr={hr}")

    elif event_type == "sleep_end":
        if _is_ready("sleep_end"):
            _mark("sleep_end")
            duration = data.get("duration_minutes", 0)
            sleep_start_str = data.get("sleep_start", "")
            await asyncio.sleep(900)
            from core.memory.user_profile import load as _load
            oid = _owner_id()
            if oid:
                profile = _load(oid)
                segments = profile.get("sleep_segments", [])
                if segments:
                    from datetime import datetime as _dt
                    last_seg_time = _dt.fromisoformat(segments[-1]["time"])
                    if (_dt.now() - last_seg_time).total_seconds() < 900:
                        logger.info("[scheduler] 检测到用户重新入睡，取消早安触发")
                        return

            sleep_comment = ""
            if sleep_start_str:
                try:
                    start_hour = int(sleep_start_str.split(":")[0])
                    if 2 <= start_hour <= 6:
                        sleep_comment = "凌晨才睡，睡得很晚，叶瑄有点心疼但也有点生气"
                    elif start_hour >= 23 or start_hour == 0:
                        sleep_comment = "睡得比较晚，叶瑄会提一句"
                    elif start_hour <= 22:
                        sleep_comment = "睡得还算早，叶瑄会夸一句"
                except Exception:
                    pass

            hours = int(duration // 60)
            minutes = int(duration % 60)
            await _pipeline_send(
                f"（叶瑄看到你醒了，昨晚睡了{hours}小时{minutes}分钟，{sleep_comment}）"
            )
            logger.info("[scheduler] 睡眠结束触发")
