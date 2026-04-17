"""
角色对用户的认知文件
─────────────────────────────────────────────────────
叶瑄对每个用户维护一个"认知 Markdown 文件"，
记录她觉得重要的事情、用户的特点、两人的重要时刻。

存储位置：
  data/character_growth/叶瑄_{user_id}.md

更新机制：
  每 20 轮对话触发一次，把最近3天的日志喂给 LLM，
  让 LLM 以叶瑄的视角更新这个文件（全量覆写，300字以内）。

轮数计数器保存在内存里（重启清零，无所谓，只会少触发一次）。
"""

import logging
from pathlib import Path

from core.error_handler import log_error

logger = logging.getLogger(__name__)

# 认知文件根目录
_GROWTH_ROOT = Path("data/character_growth")

# 内存中的轮数计数器：{user_id: 轮数}
# 每次 should_update() 返回 True 后会重置
_round_counter: dict[str, int] = {}

# 每多少轮触发一次更新（与 short_term 摘要同频）
_UPDATE_EVERY_N = 20


def _growth_file(character_name: str, user_id: str) -> Path:
    """返回认知文件路径，文件名格式：叶瑄_{user_id}.md"""
    # 清理文件名里可能有的特殊字符
    safe_char = "".join(c for c in character_name if c.isalnum() or c in "-_")
    safe_user = "".join(c for c in user_id if c.isalnum() or c in "-_")
    return _GROWTH_ROOT / f"{safe_char}_{safe_user}.md"


def load(character_name: str, user_id: str) -> str:
    """
    读取叶瑄对该用户的认知文件内容。
    文件不存在时返回空字符串，不报错。

    参数：
        character_name - 角色名（如"叶瑄"）
        user_id        - 用户 QQ 号

    返回：
        认知文件的文本内容，空则返回 ""
    """
    path = _growth_file(character_name, user_id)
    try:
        if path.exists():
            return path.read_text(encoding="utf-8").strip()
    except Exception as e:
        log_error("character_growth.load", e)
    return ""


async def update(
    character_name: str,
    user_id: str,
    event_log_content: str,
    llm_client,
):
    """
    让 LLM 以叶瑄的视角，根据最近对话日志更新认知文件。
    全量覆写文件（不追加），300字以内。

    参数：
        character_name    - 角色名（如"叶瑄"）
        user_id           - 用户 QQ 号
        event_log_content - get_recent_days() 返回的最近日志文本
        llm_client        - core.llm_client 模块
    """
    if not event_log_content.strip():
        logger.debug(f"[character_growth] 日志为空，跳过更新: {user_id}")
        return

    current = load(character_name, user_id)

    prompt = [
        {
            "role": "system",
            "content": (
                f"你是{character_name}，根据以下最近的对话记录，"
                f"更新你对这个人的了解和认知。\n"
                f"保持{character_name}的视角和语气，控制在300字以内，"
                f"记录你觉得重要的事情、这个人的特点、"
                f"你们之间发生过的重要时刻。\n"
                f"只输出更新后的认知内容本身，不要任何解释或标题。"
            ),
        },
        {
            "role": "user",
            "content": (
                f"现有认知：\n{current if current else '（暂无）'}\n\n"
                f"最新对话：\n{event_log_content}"
            ),
        },
    ]

    try:
        new_content = await llm_client.chat(prompt)
        new_content = new_content.strip()
        if not new_content:
            logger.warning(f"[character_growth] LLM 返回空内容，跳过写入: {user_id}")
            return

        # 确保目录存在
        _GROWTH_ROOT.mkdir(parents=True, exist_ok=True)

        path = _growth_file(character_name, user_id)
        path.write_text(new_content, encoding="utf-8")
        logger.info(f"[character_growth] 认知文件已更新: {path.name}（{len(new_content)}字）")

    except Exception as e:
        log_error("character_growth.update", e)


def should_update(user_id: str) -> bool:
    """
    判断是否到了触发更新的时机（每 20 轮一次）。
    每次调用都会让计数器 +1；到达阈值时重置并返回 True。

    参数：
        user_id - 用户 QQ 号

    返回：
        True 表示本轮应触发 update()
    """
    _round_counter[user_id] = _round_counter.get(user_id, 0) + 1
    if _round_counter[user_id] >= _UPDATE_EVERY_N:
        _round_counter[user_id] = 0
        return True
    return False


class CharacterGrowth:
    """
    CharacterGrowth 类封装，供外部按类方式导入使用。
    所有方法都代理到模块级函数。
    """

    def load(self, character_name: str, user_id: str) -> str:
        return load(character_name, user_id)

    async def update(
        self,
        character_name: str,
        user_id: str,
        event_log_content: str,
        llm_client,
    ):
        await update(character_name, user_id, event_log_content, llm_client)

    def should_update(self, user_id: str) -> bool:
        return should_update(user_id)
