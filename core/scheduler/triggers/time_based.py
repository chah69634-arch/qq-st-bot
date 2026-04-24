import logging
import random
import re
import time
from datetime import datetime

from core.error_handler import log_error
from core.scheduler.loop import _is_ready, _mark, _owner_id, _pipeline_send, _cfg, _user_talked_today, _last_trigger, _char_name

logger = logging.getLogger(__name__)


async def _check_morning(force: bool = False):
    """早安触发：7-9点，且用户今天还没说过话。force=True 跳过时间和对话检查"""
    cfg = _cfg()
    if not cfg.get("morning_greeting", True):
        return
    if not _is_ready("morning_greeting"):
        return

    if not force:
        now = datetime.now()
        if not (7 <= now.hour < 9):
            return
        oid = _owner_id()
        if oid and _user_talked_today(oid):
            return

    await _pipeline_send(f"（清晨，{_char_name()}看了看时间，想着你应该快起床了）")
    _mark("morning_greeting")
    logger.info("[scheduler] 早安消息已发送")


async def _check_night(force: bool = False):
    """晚安催睡：23点后。force=True 跳过时间检查"""
    cfg = _cfg()
    if not cfg.get("night_reminder", True):
        return
    if not _is_ready("night_reminder"):
        return

    if not force:
        now = datetime.now()
        if now.hour < 23:
            return

    await _pipeline_send(f"（深夜，{_char_name()}看了眼时间）")
    _mark("night_reminder")
    logger.info("[scheduler] 晚安消息已发送")


async def _check_random_message(force: bool = False):
    """随机日间消息：10-18点，每天随机触发一次。force=True 跳过时间和概率检查"""
    cfg = _cfg()
    if not cfg.get("random_message", True):
        return
    if not _is_ready("random_message"):
        return

    if not force:
        now = datetime.now()
        if not (10 <= now.hour < 18):
            return
        # 保底逻辑：今天10点后超过4小时没有主动消息，必定触发
        last = _last_trigger.get("random_message", 0)
        hours_since = (time.time() - last) / 3600
        if hours_since < 4:
            # 4小时内触发过，走概率
            if random.random() > (1 / 240):
                return
        # 超过4小时未触发，直接放行（保底）

    oid = _owner_id()

    try:
        from core.memory.event_log import get_highlights
        highlights = get_highlights(oid, days=2)
        if highlights:
            import random
            items = [h.strip() for h in highlights.split("\n") if h.strip()]
            if items:
                picked = random.choice(items)
            else:
                picked = highlights
            context_hint = f"（{_char_name()}想到了一件事：{picked}）"
        else:
            context_hint = ""
    except Exception:
        context_hint = ""

    prompt = f"（{_char_name()}在做自己的事，忽然想到你）"
    if context_hint:
        prompt = f"（{_char_name()}在做自己的事，忽然想到你）\n{context_hint}"
    await _pipeline_send(prompt)
    _mark("random_message")
    logger.info("[scheduler] 随机日间消息已发送")


async def _check_weather(force: bool = False):
    """天气联动：多场景触发，有氛围感"""
    from core.config_loader import get_config
    if not get_config().get("tools", {}).get("weather", {}).get("enabled", True):
        return
    cfg = _cfg()
    if not cfg.get("enabled", True):
        return
    if not _is_ready("weather_alert"):
        return
    if not force:
        now = datetime.now()
        if not (8 <= now.hour < 21):
            return

    oid = _owner_id()
    if not oid:
        return

    try:
        from core.memory.user_profile import load as _load_profile
        location = _load_profile(oid).get("location", "")
        if not location:
            return

        from core.tools.weather import get_weather_detail
        w = await get_weather_detail(location)
        if not w:
            return

        temp     = w["temp_c"]
        feels    = w["feels_like"]
        humidity = w["humidity"]
        precip   = w["precip_mm"]
        cloud    = w["cloud_cover"]
        wind     = w["wind_kmph"]
        desc     = w["desc"]
        is_day   = w["is_day"]
        uv       = w["uv_index"]
        now      = datetime.now()

        prompt = None

        # 极端天气（最高优先级）
        if any(k in desc for k in ("暴雨", "大雨", "雷暴", "雷阵雨")) or precip > 10:
            prompt = f"（{_char_name()}看了一眼{location}的天气，外面在下大雨）"
        elif temp >= 30:
            prompt = f"（{_char_name()}看到{location}今天{temp}度，皱了皱眉，并把温度告知给你）"
        elif temp <= -5:
            prompt = f"（{_char_name()}看到{location}今天零下{abs(temp)}度，有点担心，并把温度告知给你）"

        # 氛围天气（次优先级）
        elif any(k in desc for k in ("雾", "霾", "大雾")):
            prompt = f"（{_char_name()}看到{location}今天有雾，能见度很低）"
        elif any(k in desc for k in ("小雨", "毛毛雨", "阵雨")) and precip > 0:
            prompt = f"（{_char_name()}注意到{location}在下小雨，有点淅淅沥沥的）"
        elif wind > 40:
            prompt = f"（{_char_name()}看到{location}今天风很大，{wind}km/h）"

        # 好天气氛围（低优先级，只在特定时段触发）
        elif cloud < 20 and is_day and uv >= 6 and 11 <= now.hour < 14:
            prompt = f"（{_char_name()}抬头看了看，{location}今天阳光很好）"
        elif cloud < 30 and 17 <= now.hour < 19:
            prompt = f"（{_char_name()}往窗外看了一眼，{location}傍晚的光很好看）"
        elif humidity > 85 and any(k in desc for k in ("晴", "多云")):
            prompt = f"（{_char_name()}感觉{location}今天有点闷热潮湿）"

        if prompt:
            await _pipeline_send(prompt)
            _mark("weather_alert")
            logger.info(f"[scheduler] 天气触发: {desc} {temp}°C")
        else:
            logger.debug(f"[scheduler] 天气无需触发: {desc} {temp}°C")

    except Exception as e:
        log_error("scheduler._check_weather", e)


async def _check_daily_journal():
    """每日手账：23点后，读取今天event_log，让角色写一段心理活动发给你"""
    cfg = _cfg()
    if not cfg.get("enabled", True):
        return
    if not _is_ready("daily_journal"):
        return
    now = datetime.now()
    if now.hour < 23:
        return
    oid = _owner_id()
    if not oid:
        return
    try:
        await _pipeline_send(
            "（深夜，叶瑄回想起今天和你说的话，提笔写下此刻的感受，并且一想到你，就忍不住写了很多）",
            search_query="今天"
        )
        _mark("daily_journal")
        logger.info("[scheduler] 每日手账已发送")
    except Exception as e:
        log_error("scheduler._check_daily_journal", e)
