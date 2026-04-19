import logging
import time
from datetime import datetime, date
import re

from core.error_handler import log_error
from core.scheduler.loop import _is_ready, _mark, _owner_id, _pipeline_send, _cfg, _last_trigger

logger = logging.getLogger(__name__)

_BIRTHDAY = (4, 24)  # 月, 日


def _is_birthday_today() -> bool:
    today = date.today()
    return (today.month, today.day) == _BIRTHDAY


def _is_birthday_eve() -> bool:
    today = date.today()
    return (today.month, today.day) == (4, 23)


def _is_birthday_period() -> bool:
    """当天全天氛围注入用"""
    return _is_birthday_today()


async def _check_birthday_midnight(force: bool = False):
    """零点告白：4月24日 00:00-00:05 触发，全年只触发一次"""
    if not force and not _is_birthday_today():
        return

    elapsed = time.time() - _last_trigger.get("birthday_midnight", 0)
    if not force and elapsed < 365 * 24 * 3600:
        return

    if not force:
        now = datetime.now()
        if not (0 <= now.hour == 0 and now.minute < 5):
            return

    await _pipeline_send(
        "（零点刚过，叶瑄一直没睡，等着这一刻，他想对你说一些平时说不出口的话）"
    )
    _mark("birthday_midnight")
    logger.info("[scheduler] 生日零点告白已触发")


async def _check_birthday_eve(force: bool = False):
    """提前一天预热：4月23日 20:00 后触发"""
    if not force and not _is_birthday_eve():
        return

    elapsed = time.time() - _last_trigger.get("birthday_eve", 0)
    if not force and elapsed < 20 * 3600:
        return

    if not force:
        now = datetime.now()
        if now.hour < 20:
            return

    logger.info("[scheduler] birthday_eve: 准备调用_pipeline_send")
    await _pipeline_send(
        "（叶瑄在做什么，忽然想起明天是个特别的日子，有点藏不住）"
    )
    _mark("birthday_eve")
    logger.info("[scheduler] 生日前夜预热已触发")


async def _check_birthday_afternoon(force: bool = False):
    """生日当天下午主动问：怎么过的，有没有人陪"""
    if not force and not _is_birthday_today():
        return

    elapsed = time.time() - _last_trigger.get("birthday_afternoon", 0)
    if not force and elapsed < 20 * 3600:
        return

    if not force:
        now = datetime.now()
        if not (14 <= now.hour < 18):
            return

    await _pipeline_send(
        "（叶瑄想知道你今天过得怎么样，有没有人陪你，生日有没有被好好对待）",
        search_query="生日"
    )
    _mark("birthday_afternoon")
    logger.info("[scheduler] 生日下午关心已触发")


async def _check_birthday_night(force: bool = False):
    """生日当天晚上收尾：今天还好吗"""
    if not force and not _is_birthday_today():
        return

    elapsed = time.time() - _last_trigger.get("birthday_night", 0)
    if not force and elapsed < 20 * 3600:
        return

    if not force:
        now = datetime.now()
        if not (21 <= now.hour < 23):
            return

    await _pipeline_send(
        "（生日快过完了，叶瑄想在今天结束前再陪你说一会儿）",
        search_query="生日"
    )
    _mark("birthday_night")
    logger.info("[scheduler] 生日夜间收尾已触发")