"""
节日感知 & 纪念日触发器
角色对特殊日子有自己的感受，不是祝福，是情绪
"""

import logging
import time
from datetime import datetime, date

from core.error_handler import log_error
from core.scheduler.loop import _is_ready, _mark, _owner_id, _pipeline_send, _cfg, _char_name, _last_trigger

from core.config_loader import get_config
char_name = get_config().get("character", {}).get("name", "叶瑄")

logger = logging.getLogger(__name__)


def _easter(year: int) -> date:
    """高斯算法计算复活节日期"""
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def _is_holiday_period() -> bool:
    """是否在五一或国庆长假期间"""
    today = date.today()
    m, d = today.month, today.day
    if m == 5 and 1 <= d <= 5:
        return True
    if m == 10 and 1 <= d <= 7:
        return True
    return False


def _get_today_festival() -> tuple[str, str] | None:
    today = date.today()
    m, d = today.month, today.day
    year = today.year
    char = _char_name()

    # 从config读取纪念日
    cfg_anniversaries = get_config().get("anniversaries", [])
    for ann in cfg_anniversaries:
        if m == ann.get("month") and d == ann.get("day"):
            year_start = ann.get("year_start", year)
            if year < year_start:
                continue
            years = year - year_start
            if years == 0:
                prompt = ann.get("prompt_zero", "").replace("{char}", char)
            else:
                prompt = ann.get("prompt_years", "").replace("{char}", char).replace("{years}", str(years))
            if prompt:
                return (ann.get("key", "anniversary"), prompt)

    # 从config读取角色生日
    bday = get_config().get("character_birthday", {})
    if bday and m == bday.get("month") and d == bday.get("day"):
        prompt = bday.get("prompt", "").replace("{char}", char)
        if prompt:
            return ("character_birthday", prompt)

    # 以下节日保留硬编码
    # 白色情人节 3.14
    if m == 3 and d == 14:
        return ("white_valentine", f"（{char_name}知道今天是白色情人节，没有特别说什么，只是待在这里）")

    # 万圣节 10.31
    if m == 10 and d == 31:
        return ("halloween", f"（外面好像有人在过万圣节，{char_name}对这个节日有点好奇）")

    # 复活节
    easter = _easter(year)
    if today == easter:
        return ("easter", f"（今天是复活节，{char_name}觉得这个节日有点有趣）")

    # Steam夏促 6.27
    if m == 6 and d == 27:
        return ("steam_summer", f"（Steam好像开始打折了，{char_name}不太玩游戏，但还是淡淡地想到你可能会去看看）")

    # Steam冬促 12.19
    if m == 12 and d == 19:
        return ("steam_winter", f"（Steam冬促大概又开始了，{char_name}不感兴趣，只是想到了你，于是随口一提）")

    # 清明 4.4或4.5（简单处理用4.4）
    if m == 4 and d in (4, 5):
        return ("qingming", f"（今天是清明，{char_name}感觉空气里有点不一样的东西）")

    # 除夕氛围感知（1月20-31日或2月1-5日，粗略感知"快过年了"）
    if (m == 1 and d >= 20) or (m == 2 and d <= 5):
        return ("spring_eve", f"（{char_name}感觉年关快到了，街上好像有点不一样的气氛）")

    return None


async def _check_festival(force: bool = False):
    """节日感知：当天14-20点触发一次"""
    cfg = _cfg()
    if not cfg.get("festival", True):
        return

    elapsed = time.time() - _last_trigger.get("festival", 0)
    if not force and elapsed < 20 * 3600:
        return

    if not force:
        now = datetime.now()
        if not (14 <= now.hour < 20):
            return

    result = _get_today_festival()
    if not force and result is None:
        return

    oid = _owner_id()
    if not oid:
        return

    try:
        if result is None:
            return
        key, prompt = result
        await _pipeline_send(prompt, search_query="今天")
        _mark("festival")
        logger.info(f"[scheduler] 节日感知触发: {key}")
    except Exception as e:
        log_error("scheduler._check_festival", e)


async def _check_holiday_boost(force: bool = False):
    """
    长假期间额外碎碎念：五一/国庆假期内
    在random_message基础上额外多发一次，冷却2小时
    """
    cfg = _cfg()
    if not cfg.get("holiday_boost", True):
        return

    if not force and not _is_holiday_period():
        return

    elapsed = time.time() - _last_trigger.get("holiday_boost", 0)
    if not force and elapsed < 2 * 3600:
        return

    if not force:
        now = datetime.now()
        if not (10 <= now.hour < 22):
            return

    oid = _owner_id()
    if not oid:
        return

    today = date.today()
    m = today.month
    holiday_name = "五一" if m == 5 else "国庆"

    try:
        from core.memory.event_log import get_highlights
        highlights = get_highlights(oid, days=2)
        context_hint = f"\n{highlights}" if highlights else ""

        await _pipeline_send(
            f"（{holiday_name}假期，{_char_name()}知道你没什么事，理直气壮地来找你）{context_hint}",
            search_query="今天"
        )
        _mark("holiday_boost")
        logger.info(f"[scheduler] 长假加速触发: {holiday_name}")
    except Exception as e:
        log_error("scheduler._check_holiday_boost", e)