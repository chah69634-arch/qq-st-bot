import logging
import time
from datetime import datetime, date

from core.error_handler import log_error
from core.scheduler.loop import (
    _is_ready, _mark, _owner_id, _pipeline_send, _cfg, _char_name,
    _last_diary_share, _scheduler_start_time,
)

logger = logging.getLogger(__name__)


async def _check_diary_reminder():
    """昨天没写日记时，叶瑄提醒"""
    cfg = _cfg()
    if not cfg.get("enabled", True):
        return
    if not _is_ready("diary_reminder"):
        return
    now = datetime.now()
    if not (9 <= now.hour < 12):
        return
    try:
        from core.tools.diary_reader import yesterday_missing
        if yesterday_missing():
            from datetime import timedelta
            yesterday = (date.today() - timedelta(days=1)).strftime("%m月%d日")
            await _pipeline_send(
                f"（{_char_name()}翻到了{yesterday}的日期）",
                search_query="日记"
            )
            _mark("diary_reminder")
            logger.info("[scheduler] 日记缺失提醒已发送")
    except Exception as e:
        log_error("scheduler._check_diary_reminder", e)


async def _check_diary_inject():
    """每6小时读取最近日记，存入diary_context独立存储，不写event_log"""
    cfg = _cfg()
    if not cfg.get("enabled", True):
        return
    if not _is_ready("diary_inject"):
        return
    oid = _owner_id()
    if not oid:
        return
    try:
        from core.tools.diary_reader import read_recent
        from core.memory.diary_context import save
        text = read_recent(days=2)
        if text:
            save(oid, text)
            _mark("diary_inject")
            logger.info("[scheduler] 日记内容已存入diary_context")
    except Exception as e:
        log_error("scheduler._check_diary_inject", e)


async def _check_diary_share_reminder():
    """超过3天没看到日记分享时，叶瑄不经意提一句"""
    cfg = _cfg()
    if not cfg.get("enabled", True):
        return
    if time.time() - _scheduler_start_time < 300:
        return
    if not _is_ready("diary_share_reminder"):
        return
    now = datetime.now()
    if now.hour < 22:
        return
    if _last_diary_share > 0:
        from datetime import date as _date
        if datetime.fromtimestamp(_last_diary_share).date() == _date.today():
            return
    if time.time() - _last_diary_share < 259200:  # 3天内分享过就跳过
        return
    oid = _owner_id()
    if not oid:
        return
    try:
        await _pipeline_send(
            f"（{_char_name()}发现自己好几天没看到你写的东西了）",
            search_query="日记"
        )
        _mark("diary_share_reminder")
        logger.info("[scheduler] 日记分享提醒已发送")
    except Exception as e:
        log_error("scheduler._check_diary_share_reminder", e)
