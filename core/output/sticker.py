"""
表情包发送模块
LLM判断情绪类别，随机抽取对应文件夹的图片发送
概率极低，叶瑄偶尔才会发
"""

import logging
import random
from pathlib import Path

from core.error_handler import log_error

logger = logging.getLogger(__name__)

_STICKER_ROOT = Path("assets/stickers")

_EMOTION_LABELS = ["无奈", "心疼", "开心", "委屈", "害羞", "沉默"]

# 触发概率，叶瑄不常发表情包
_TRIGGER_PROB = 0.06


def _pick_sticker(emotion: str) -> str | None:
    """从对应情绪文件夹随机抽一张图片，返回绝对路径"""
    folder = _STICKER_ROOT / emotion
    if not folder.exists():
        return None
    files = [f for f in folder.iterdir() if f.suffix.lower() in (".jpg", ".jpeg", ".png", ".gif")]
    if not files:
        return None
    return str(random.choice(files).resolve())


async def maybe_send_sticker(reply: str, target_id: str, is_group: bool = False):
    """
    根据回复内容判断情绪，小概率发一张表情包。
    在post_process里调用，失败静默。
    """
    try:
        if random.random() > _TRIGGER_PROB:
            return

        from core import llm_client
        judge_prompt = [
            {
                "role": "system",
                "content": (
                    "判断下面这句话的情绪，只从以下六个标签中选一个输出，不要输出任何其他内容：\n"
                    "无奈、心疼、开心、委屈、害羞、沉默"
                ),
            },
            {
                "role": "user",
                "content": reply[:200],
            },
        ]

        emotion = (await llm_client.chat(judge_prompt)).strip()
        if emotion not in _EMOTION_LABELS:
            return

        path = _pick_sticker(emotion)
        if not path:
            return

        from core.qq_adapter import send_image
        await send_image(target_id, path, is_group)
        logger.info(f"[sticker] 发送表情包: {emotion} -> {path}")

    except Exception as e:
        log_error("sticker.maybe_send_sticker", e)
