"""
消息队列模块
每个 session_key（私聊=user_id，群聊=group_id）独立的 asyncio.Queue
同一会话串行处理，不同会话并行处理
防止并发读写同一用户的历史文件
"""

import asyncio
import logging
from typing import Any, Callable, Coroutine

from core.error_handler import log_error

logger = logging.getLogger(__name__)

# 每个 session_key 对应一个队列
_queues: dict[str, asyncio.Queue] = {}
# 每个 session_key 对应一个处理任务
_tasks: dict[str, asyncio.Task] = {}
# 消息处理器回调（由 main.py 注入）
_handler: Callable | None = None


def set_handler(handler: Callable):
    """
    注入消息处理函数

    handler 签名：async def handler(message: dict) -> None
    其中 message 是统一消息结构：
    {user_id, group_id, content, sender_name, timestamp}
    """
    global _handler
    _handler = handler


def get_session_key(message: dict) -> str:
    """
    根据消息类型生成 session_key
    私聊：使用 user_id（保证私聊独立）
    群聊：使用 group_id（同一群内串行）
    """
    if message.get("group_id"):
        return f"group_{message['group_id']}"
    return f"user_{message['user_id']}"


async def enqueue(message: dict):
    """
    将消息放入对应会话的队列

    如果该会话没有处理任务在运行，则启动一个新任务
    """
    session_key = get_session_key(message)

    # 确保队列存在
    if session_key not in _queues:
        _queues[session_key] = asyncio.Queue()

    # 入队
    await _queues[session_key].put(message)
    logger.debug(f"[message_queue] 消息入队 {session_key}，队列长度: {_queues[session_key].qsize()}")

    # 确保该会话有一个活跃的处理任务
    if session_key not in _tasks or _tasks[session_key].done():
        _tasks[session_key] = asyncio.create_task(_process_session(session_key))


async def _process_session(session_key: str):
    """
    持续处理某个会话队列中的消息，直到队列为空

    同一会话内消息严格串行：上一条处理完才处理下一条
    """
    queue = _queues.get(session_key)
    if not queue:
        return

    while not queue.empty():
        message = await queue.get()
        try:
            if _handler:
                await _handler(message)
            else:
                logger.warning(f"[message_queue] 未设置消息处理器，消息被丢弃: {message}")
        except Exception as e:
            log_error(f"message_queue._process_session[{session_key}]", e)
            logger.error(f"[message_queue] 消息处理异常（已捕获）: {type(e).__name__}: {e}")
        except BaseException as e:
            # 捕获 asyncio.CancelledError 等 BaseException，防止静默丢失
            # 注意：finally 会调用 task_done()，此处不重复调用
            logger.error(
                f"[message_queue] 消息处理遇到 BaseException: {type(e).__name__}: {e}"
            )
            raise  # 重新抛出，让任务正常取消
        finally:
            queue.task_done()

    # 队列清空，任务自然结束
    # 下次有新消息入队时，会重新启动任务
    logger.debug(f"[message_queue] 会话 {session_key} 队列已清空，处理任务结束")


def queue_size(session_key: str) -> int:
    """获取指定会话的待处理消息数（用于监控）"""
    q = _queues.get(session_key)
    return q.qsize() if q else 0


def active_sessions() -> list[str]:
    """返回当前有活跃任务的 session_key 列表（用于监控）"""
    return [key for key, task in _tasks.items() if not task.done()]


class MessageQueue:
    """消息队列类，封装模块级函数，供外部按类方式导入使用"""

    def set_handler(self, handler: Callable):
        set_handler(handler)

    async def enqueue(self, message: dict):
        await enqueue(message)

    def active_sessions(self) -> list[str]:
        return active_sessions()

    def queue_size(self, session_key: str) -> int:
        return queue_size(session_key)

    @staticmethod
    def get_session_key(message: dict) -> str:
        return get_session_key(message)
