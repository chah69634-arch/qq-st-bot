"""
群聊蒸馏工具
读取指定群的消息记录，调用 LLM 生成群聊摘要。

函数：
  distill(group_id, llm_client=None) -> str
"""

import logging

from core.error_handler import log_error

logger = logging.getLogger(__name__)

_DISTILL_PROMPT_TEMPLATE = (
    "分析以下群聊记录，用叶瑄的视角总结：\n"
    "1. 群里最近在聊什么话题\n"
    "2. 活跃成员的性格特点（各一句话）\n"
    "3. 有什么有趣或值得记住的发言\n"
    "请用简洁的中文回答，300字以内。\n\n"
    "群聊记录：\n{chat_log}"
)


async def distill(group_id: str, llm_client=None) -> str:
    """
    对指定群的消息记录进行 LLM 蒸馏，返回摘要字符串。

    参数：
        group_id   — 群号字符串
        llm_client — 可选，传入 llm_client 模块；默认使用 core.llm_client
    返回：
        摘要文本，出错时返回错误描述
    """
    from core.memory.group_context import get_recent

    messages = get_recent(group_id)
    if not messages:
        return f"群 {group_id} 暂无消息记录，无法蒸馏。"

    # 格式化消息列表为纯文本
    lines = []
    for m in messages:
        ts   = m.get("timestamp", "")
        name = m.get("sender_name", "?")
        text = m.get("content", "")
        prefix = f"[{ts}] " if ts else ""
        lines.append(f"{prefix}{name}: {text}")
    chat_log = "\n".join(lines)

    prompt_messages = [
        {
            "role": "user",
            "content": _DISTILL_PROMPT_TEMPLATE.format(chat_log=chat_log),
        }
    ]

    try:
        if llm_client is None:
            from core import llm_client as _lc
            result = await _lc.chat(prompt_messages)
        else:
            result = await llm_client.chat(prompt_messages)
        return result or "（LLM 未返回内容）"
    except Exception as e:
        log_error("group_distill.distill", e)
        return f"蒸馏失败：{type(e).__name__}: {e}"
