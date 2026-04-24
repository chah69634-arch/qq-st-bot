"""
请勿打扰状态
用户进入学习/开会/工作状态时，调度器暂停主动消息3小时（已冻结）
"""

import logging
import time

from core.error_handler import log_error

logger = logging.getLogger(__name__)

# 请勿打扰状态存储 {user_id: expire_timestamp}
_dnd_expire: dict[str, float] = {}

# 触发关键词
_DND_KEYWORDS = [
    "学习", "开会", "上班", "工作", "在忙", "忙着",
    "复习", "备考", "做题", "写作业", "写报告",
]

_DND_DURATION = 3 * 3600  # 3小时


def set_dnd(user_id: str):
    """设置请勿打扰状态，3小时后自动过期"""
    _dnd_expire[user_id] = time.time() + _DND_DURATION
    logger.info(f"[dnd] 用户 {user_id} 进入请勿打扰状态，3小时内调度器暂停主动消息")


def clear_dnd(user_id: str):
    """手动清除请勿打扰状态"""
    _dnd_expire.pop(user_id, None)
    logger.info(f"[dnd] 用户 {user_id} 请勿打扰状态已清除")


def is_dnd(user_id: str) -> bool:
    """检查用户是否处于请勿打扰状态"""
    expire = _dnd_expire.get(user_id)
    if not expire:
        return False
    if time.time() > expire:
        _dnd_expire.pop(user_id, None)
        return False
    return True


def detect_and_set(user_id: str, content: str):
    """
    检测用户消息是否包含请勿打扰关键词
    包含则设置状态，同时检测结束关键词清除状态
    """
    end_keywords = ["下课", "散会", "下班", "忙完", "做完了", "写完了", "结束了", "搞定了"]
    for kw in end_keywords:
        if kw in content:
            clear_dnd(user_id)
            return

    for kw in _DND_KEYWORDS:
        if kw in content:
            set_dnd(user_id)
            return
