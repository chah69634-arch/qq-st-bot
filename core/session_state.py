"""
会话状态管理模块
追踪每个会话（私聊/群聊）的当前交互状态
状态机：normal → waiting_confirm / waiting_input → normal
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any

from core.config_loader import get_config

logger = logging.getLogger(__name__)


class SessionState:
    """
    单会话的状态对象

    状态说明：
        normal          - 正常聊天状态
        waiting_confirm - 等待用户输入"确认"来执行高危工具
        waiting_input   - 等待用户补充工具所需参数
    """

    NORMAL = "normal"
    WAITING_CONFIRM = "waiting_confirm"
    WAITING_INPUT = "waiting_input"

    def __init__(self):
        self.status: str = self.NORMAL
        self.pending_tool: str | None = None       # 待确认/待补全的工具名
        self.pending_args: dict | None = None      # 待确认/待补全的工具参数
        self.pending_arg_key: str | None = None    # waiting_input 时缺少的参数名
        self.last_active: datetime = datetime.now()

    def update_active(self):
        """每次交互都更新活跃时间"""
        self.last_active = datetime.now()

    def is_expired(self, timeout_minutes: int) -> bool:
        """判断会话是否超时（超过 timeout_minutes 分钟没有交互）"""
        return datetime.now() - self.last_active > timedelta(minutes=timeout_minutes)

    def set_waiting_confirm(self, tool_name: str, tool_args: dict):
        """进入等待确认状态，挂起工具调用"""
        self.status = self.WAITING_CONFIRM
        self.pending_tool = tool_name
        self.pending_args = tool_args
        self.pending_arg_key = None
        self.update_active()

    def set_waiting_input(self, tool_name: str, partial_args: dict, missing_key: str):
        """进入等待输入状态，等待用户补充参数"""
        self.status = self.WAITING_INPUT
        self.pending_tool = tool_name
        self.pending_args = partial_args
        self.pending_arg_key = missing_key
        self.update_active()

    def clear(self):
        """重置为正常状态"""
        self.status = self.NORMAL
        self.pending_tool = None
        self.pending_args = None
        self.pending_arg_key = None
        self.update_active()


# 全局状态存储：{session_key: SessionState}
_states: dict[str, SessionState] = {}
# 清理定时任务句柄
_cleanup_task: asyncio.Task | None = None


def get(session_key: str) -> SessionState:
    """
    获取会话状态，不存在则自动创建

    session_key: 私聊用 user_id，群聊用 group_id
    """
    if session_key not in _states:
        _states[session_key] = SessionState()
    state = _states[session_key]
    state.update_active()
    return state


def set_state(session_key: str, state: SessionState):
    """更新会话状态"""
    _states[session_key] = state


def clear(session_key: str):
    """清除会话状态，下次 get 时重新创建"""
    if session_key in _states:
        _states[session_key].clear()


async def _cleanup_loop():
    """后台任务：定期清理超时的会话状态，释放内存"""
    while True:
        try:
            await asyncio.sleep(60)  # 每分钟检查一次
            cfg = get_config()
            timeout = cfg.get("session", {}).get("timeout_minutes", 10)
            expired_keys = [
                key for key, state in _states.items()
                if state.is_expired(timeout) and state.status != SessionState.NORMAL
            ]
            for key in expired_keys:
                _states[key].clear()
                logger.debug(f"[session_state] 会话 {key} 已超时，状态重置")
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"[session_state] 清理循环出错: {e}")


def start_cleanup_task():
    """启动后台清理任务（在 main.py 中调用一次）"""
    global _cleanup_task
    if _cleanup_task is None or _cleanup_task.done():
        _cleanup_task = asyncio.create_task(_cleanup_loop())
        logger.info("[session_state] 超时清理任务已启动")
