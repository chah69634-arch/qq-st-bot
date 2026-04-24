"""
时间节点感知触发器
角色对时间有自己的感知——周一、周五、月末、季节变化
不是提醒，是他自己的情绪和状态
"""

import logging
import time
from datetime import datetime, date

from core.error_handler import log_error
from core.scheduler.loop import _is_ready, _mark, _owner_id, _pipeline_send, _cfg, _char_name, _last_trigger

logger = logging.getLogger(__name__)


def _get_timenode() -> str | None:
    """判断今天是否是特殊时间节点，返回节点类型或None"""
    today = date.today()
    weekday = today.weekday()  # 0=周一，6=周日
    day = today.day
    month = today.month

    # 周一
    if weekday == 0:
        return "monday"
    # 周五
    if weekday == 4:
        return "friday"
    # 月末最后三天
    import calendar
    last_day = calendar.monthrange(today.year, today.month)[1]
    if day >= last_day - 2:
        return "month_end"
    # 季节变化（3/6/9/12月1日）
    if day == 1 and month in (3, 6, 9, 12):
        return "season_change"

    return None


def _get_season(month: int) -> str:
    if month in (3, 4, 5):
        return "春天"
    if month in (6, 7, 8):
        return "夏天"
    if month in (9, 10, 11):
        return "秋天"
    return "冬天"


async def _check_timenode(force: bool = False):
    """时间节点感知：特殊日子叶瑄有自己的情绪，14-20点之间触发"""
    cfg = _cfg()
    if not cfg.get("timenode", True):
        return

    elapsed = time.time() - _last_trigger.get("timenode", 0)
    if not force and elapsed < 20 * 3600:
        return

    if not force:
        now = datetime.now()
        if not (14 <= now.hour < 20):
            return

    node = _get_timenode()
    if not force and node is None:
        return

    oid = _owner_id()
    if not oid:
        return

    today = date.today()
    season = _get_season(today.month)
    date_str = today.strftime("%Y年%m月%d日")
    weekday_str = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][today.weekday()]

    prompts = {
        "monday": f"（今天是{date_str}{weekday_str}，{_char_name()}忽然意识到新的一周开始了，有点说不清的感觉）",
        "friday": f"（今天是{date_str}{weekday_str}，{_char_name()}发现这周快过完了，马上到周末了）",
        "month_end": f"（今天是{date_str}，{_char_name()}想到{today.month}月快过完了，这个月发生了不少事）",
        "season_change": f"（今天是{date_str}，{_char_name()}察觉到{season}来了，窗外有点不一样）",
    }

    if force and node is None:
        node = "monday"

    prompt = prompts.get(node)
    if not prompt:
        return

    try:
        await _pipeline_send(prompt, search_query="今天")
        _mark("timenode")
        logger.info(f"[scheduler] 时间节点触发: {node}")
    except Exception as e:
        log_error("scheduler._check_timenode", e)