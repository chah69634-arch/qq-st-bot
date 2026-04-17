"""
短期记忆模块
保留最近 N 轮对话（N = config.memory.short_term_rounds）
持久化到 data/history/{user_id}.json
"""

import json
import logging
from pathlib import Path

from core.config_loader import get_config
from core.error_handler import log_error

logger = logging.getLogger(__name__)

HISTORY_DIR = Path("data/history")


def _history_path(user_id: str) -> Path:
    """返回该用户的历史文件路径"""
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    return HISTORY_DIR / f"{user_id}.json"


def load(user_id: str) -> list[dict]:
    """
    读取用户的短期对话历史（完整历史，不做截断）

    返回格式：[{"role": "user"/"assistant", "content": "..."}, ...]
    文件不存在时返回空列表
    """
    path = _history_path(user_id)
    try:
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, list) else []
    except Exception as e:
        log_error("short_term.load", e)
    return []


def get_history(user_id: str, max_turns: int | None = None) -> list[dict]:
    """
    读取用户的短期对话历史，支持按轮数截断。

    参数：
        user_id   - 用户 QQ 号
        max_turns - 最多返回多少轮（一轮 = user + assistant 各一条）
                    None 时从 config.yaml 的 context.max_turns 读取，
                    再 fallback 到 memory.short_term_rounds，默认 20

    返回：
        截断后的消息列表，格式同 load()
    """
    if max_turns is None:
        cfg = get_config()
        # 优先读 context.max_turns，没有则读旧的 memory.short_term_rounds
        max_turns = (
            cfg.get("context", {}).get("max_turns")
            or cfg.get("memory", {}).get("short_term_rounds", 20)
        )

    history = load(user_id)
    # 每轮 = 2 条消息（user + assistant）
    max_msgs = max_turns * 2
    return history[-max_msgs:] if len(history) > max_msgs else history


def append(user_id: str, role: str, content: str):
    """
    追加一条消息到历史记录，并裁剪到最大轮数

    role: "user" 或 "assistant"
    每两条（一问一答）算一轮，实际保留 short_term_rounds * 2 条消息
    """
    cfg = get_config()
    max_rounds = cfg.get("memory", {}).get("short_term_rounds", 20)
    max_msgs = max_rounds * 2  # 每轮 = user + assistant

    history = load(user_id)
    history.append({"role": role, "content": content})

    # 超出上限时，从头部移除最早的消息
    if len(history) > max_msgs:
        history = history[-max_msgs:]

    _save(user_id, history)


def _save(user_id: str, history: list[dict]):
    """把历史记录写回磁盘"""
    path = _history_path(user_id)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log_error("short_term._save", e)


def clear(user_id: str):
    """清空指定用户的短期历史（admin 用）"""
    _save(user_id, [])


class ShortTermMemory:
    """短期记忆类，封装模块级函数，供外部按类方式导入使用"""

    def load(self, user_id: str) -> list[dict]:
        return load(user_id)

    def get_history(self, user_id: str, max_turns: int | None = None) -> list[dict]:
        return get_history(user_id, max_turns)

    def append(self, user_id: str, role: str, content: str):
        append(user_id, role, content)

    def clear(self, user_id: str):
        clear(user_id)
