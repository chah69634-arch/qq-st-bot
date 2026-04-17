"""
文本输出模块
负责将处理后的回复列表通过 QQ 发送出去
支持多段消息（超长回复分条发送）
"""

import asyncio
import logging

from core.error_handler import log_error

logger = logging.getLogger(__name__)

# 多段消息之间的发送间隔（秒），模拟真人打字节奏
_SEGMENT_DELAY = 0.5


async def send(
    target_id: str,
    segments: list[str],
    is_group: bool = False,
):
    """
    发送回复消息

    参数:
        target_id: 目标 QQ 号（私聊）或群号（群聊）
        segments:  消息段列表（来自 response_processor.process()）
        is_group:  True=群聊，False=私聊
    """
    from core import qq_adapter

    if not segments:
        logger.info("[text_output] segments 为空，没有需要发送的内容")
        return

    logger.info(
        f"[text_output] 准备发送 {len(segments)} 段消息 -> "
        f"{'群' if is_group else '私'}{target_id}"
    )

    for i, segment in enumerate(segments):
        if not segment.strip():
            logger.debug(f"[text_output] 第 {i+1} 段为空白，跳过")
            continue
        try:
            logger.info(
                f"[text_output] 发送第 {i+1}/{len(segments)} 段"
                f"（{len(segment)} 字）: {segment[:30]!r}"
            )
            await qq_adapter.send_message(target_id, segment, is_group)
            logger.info(
                f"[text_output] 第 {i+1}/{len(segments)} 段发送成功 -> {target_id}"
            )
        except Exception as e:
            log_error("text_output.send", e)
            logger.error(f"[text_output] 第 {i+1} 段发送异常: {type(e).__name__}: {e}")

        # 多段消息之间稍作停顿，避免消息顺序错乱
        if i < len(segments) - 1:
            await asyncio.sleep(_SEGMENT_DELAY)
