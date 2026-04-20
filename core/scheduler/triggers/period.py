import logging

from core.error_handler import log_error
from core.scheduler.loop import _is_ready, _mark, _owner_id, _pipeline_send, _cfg, _char_name

logger = logging.getLogger(__name__)


async def _check_period():
    """读取 last_period_date，在生理期中（0-7天）或临近下次（26-30天）时关心"""
    cfg = _cfg()
    if not cfg.get("enabled", True):
        return
    oid = _owner_id()
    if not oid:
        return
    try:
        from core.memory.user_profile import get_period_info
        info = get_period_info(oid)
        last_date_str = info.get("last_period_date")
        if not last_date_str:
            return
        from datetime import datetime, date as _date
        last_date = datetime.strptime(last_date_str, "%Y-%m-%d").date()
        days_elapsed = (_date.today() - last_date).days
        # 第一段：生理期中关心（0-7天内，冷却24小时）
        if 0 <= days_elapsed <= 7:
            if _is_ready("period_reminder"):
                await _pipeline_send(
                    f"（{_char_name()}记得你的生理期第{days_elapsed}天）",
                    search_query="生理期"
                )
                _mark("period_reminder")
                logger.info(f"[scheduler] 生理期中关心消息已发送，距上次 {days_elapsed} 天")

        # 第二段：下次预告（26-30天，冷却24小时）
        elif 26 <= days_elapsed <= 30:
            if _is_ready("period_reminder"):
                await _pipeline_send(
                    f"（{_char_name()}想起你的生理期大概快到了）",
                    search_query="生理期"
                )
                _mark("period_reminder")
                logger.info(f"[scheduler] 生理期预告消息已发送，距上次 {days_elapsed} 天")
    except Exception as e:
        log_error("scheduler._check_period", e)
