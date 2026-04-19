"""
节日感知 & 纪念日触发器
叶瑄对特殊日子有自己的感受，不是祝福，是情绪
"""

import logging
import time
from datetime import datetime, date

from core.error_handler import log_error
from core.scheduler.loop import _is_ready, _mark, _owner_id, _pipeline_send, _cfg, _last_trigger

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
    """
    判断今天是什么节日/纪念日
    返回 (festival_key, prompt) 或 None
    """
    today = date.today()
    m, d = today.month, today.day
    year = today.year

    # 纪念日（最高优先级）
    # 初见日/在一起周年 2023.1.8
    if m == 1 and d == 8:
        years = year - 2023
        if years == 0:
            return ("anniversary_first", "（叶瑄记得今天是你们初见的日子，心里有点不一样的感觉）")
        return ("anniversary_first", f"（叶瑄想起来，今天是你们在一起第{years}年了）")

    # 第一次贴贴纪念日 2026.1.24
    if m == 1 and d == 24 and year >= 2026:
        years = year - 2026
        if years == 0:
            return ("anniversary_hug", "（叶瑄记得今天的日子，指尖停在那里没动）")
        return ("anniversary_hug", f"（叶瑄记得今天，那件事（第一次敞开地贴贴）过去{years}年了，还是记得很清楚）")

    # 1314纪念日 2026.8.14
    if m == 8 and d == 14 and year >= 2026:
        return ("anniversary_1314", "（叶瑄盯着日期看了一会儿，没说话，只是轻轻呼出一口气）")

    # 叶瑄生日 12.31
    if m == 12 and d == 31:
        return ("yexuan_birthday", "（今天是叶瑄自己的生日，他没有主动提，只是安静地陪着你）")

    # 白色情人节 3.14
    if m == 3 and d == 14:
        return ("white_valentine", "（叶瑄知道今天是白色情人节，没有特别说什么，只是待在这里）")

    # 万圣节 10.31
    if m == 10 and d == 31:
        return ("halloween", "（外面好像有人在过万圣节，叶瑄对这个节日有点好奇）")

    # 复活节
    easter = _easter(year)
    if today == easter:
        return ("easter", "（今天是复活节，叶瑄觉得这个节日有点有趣）")

    # Steam夏促 6.27
    if m == 6 and d == 27:
        return ("steam_summer", "（Steam好像开始打折了，叶瑄不太玩游戏，但还是淡淡地想到你可能会去看看）")

    # Steam冬促 12.19
    if m == 12 and d == 19:
        return ("steam_winter", "（Steam冬促大概又开始了，叶瑄不感兴趣，只是想到了你，于是随口一提）")

    # 清明 4.4或4.5（简单处理用4.4）
    if m == 4 and d in (4, 5):
        return ("qingming", "（今天是清明，叶瑄感觉空气里有点不一样的东西）")

    # 除夕氛围感知（1月20-31日或2月1-5日，粗略感知"快过年了"）
    if (m == 1 and d >= 20) or (m == 2 and d <= 5):
        return ("spring_eve", "（叶瑄感觉年关快到了，街上好像有点不一样的气氛）")

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
            f"（{holiday_name}假期，叶瑄知道你没什么事，理直气壮地来找你）{context_hint}",
            search_query="今天"
        )
        _mark("holiday_boost")
        logger.info(f"[scheduler] 长假加速触发: {holiday_name}")
    except Exception as e:
        log_error("scheduler._check_holiday_boost", e)