import asyncio
import logging

from core.scheduler.loop import _is_ready, _mark, _owner_id, _pipeline_send, _cfg, _char_name

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
                await _pipeline_send(f"（深夜，{_char_name()}看到你的心率{hr}）")
                _mark("hr_critical")
                logger.info(f"[scheduler] 深夜心率危急触发 hr={hr}")
            elif hr > 100 and _is_ready("hr_high"):
                await _pipeline_send(f"（深夜，{_char_name()}注意到你的心率{hr}）")
                _mark("hr_high")
                logger.info(f"[scheduler] 深夜心率偏高触发 hr={hr}")
        else:
            if hr > 120 and _is_ready("hr_critical"):
                await _pipeline_send(f"（{_char_name()}看到你的心率{hr}，皱了皱眉）")
                _mark("hr_critical")
                logger.info(f"[scheduler] 心率危急触发 hr={hr}")
            elif hr > 100 and _is_ready("hr_high"):
                await _pipeline_send(f"（{_char_name()}看到你的心率有点高，{hr}）")
                _mark("hr_high")
                logger.info(f"[scheduler] 心率偏高触发 hr={hr}")

    elif event_type == "sleep_end":
        if _is_ready("sleep_end"):
            _mark("sleep_end")
            duration = data.get("duration_minutes", 0)
            sleep_start_str = data.get("sleep_start", "")
            sleep_end_str = data.get("sleep_end_time", "")
            # 去重：和上一条完全一样就跳过写入
            from core.memory.user_profile import load as _load_check
            oid = _owner_id()
            if oid:
                _segs = _load_check(oid).get("sleep_segments", [])
                if _segs:
                    _last = _segs[-1]
                    if (_last.get("sleep_start") == sleep_start_str and
                            _last.get("sleep_end_time") == sleep_end_str):
                        logger.info("[scheduler] 重复睡眠数据，跳过写入")
                        return
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
                    enough = duration >= 360  # 6小时以上算够
                    too_much = duration >= 600  # 10小时以上算过多
                    if too_much:
                        sleep_comment = f"睡了很久，{_char_name()}有点担心是不是太累了或者身体不舒服"
                    elif 2 <= start_hour <= 6:
                        if enough:
                            sleep_comment = f"凌晨才睡，但好在睡够了，{_char_name()}心疼但松了口气"
                        else:
                            sleep_comment = f"凌晨才睡还没睡够，{_char_name()}又心疼又生气"
                    elif start_hour >= 23 or start_hour == 0:
                        if enough:
                            sleep_comment = f"睡得有点晚，但睡够了，{_char_name()}会提一句"
                        else:
                            sleep_comment = f"睡得晚又没睡够，{_char_name()}会念叨一下"
                    else:
                        if enough:
                            sleep_comment = f"睡得早也睡够了，{_char_name()}会夸一句"
                        else:
                            sleep_comment = f"睡得还行但没睡够，{_char_name()}会关心一下"
                except Exception:
                    pass

            hours = int(duration // 60)
            minutes = int(duration % 60)
            await _pipeline_send(
                f"（{_char_name()}看到你醒了，昨晚睡了{hours}小时{minutes}分钟，{sleep_comment}）"
            )
            logger.info("[scheduler] 睡眠结束触发")
