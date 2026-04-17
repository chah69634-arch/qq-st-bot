"""
群聊上下文模块
维护每个群最近 N 条消息流（N = config.memory.group_context_lines）
持久化到 data/group_context/{group_id}.json
"""

import json
import logging
from datetime import datetime
from pathlib import Path

from core.config_loader import get_config
from core.error_handler import log_error

logger = logging.getLogger(__name__)

GROUP_CTX_DIR = Path("data/group_context")


def _ctx_path(group_id: str) -> Path:
    """返回该群的上下文文件路径"""
    GROUP_CTX_DIR.mkdir(parents=True, exist_ok=True)
    return GROUP_CTX_DIR / f"{group_id}.json"


def _load_raw(group_id: str) -> list[dict]:
    """从磁盘读取原始消息列表，出错返回空列表"""
    path = _ctx_path(group_id)
    try:
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, list) else []
    except Exception as e:
        log_error("group_context._load_raw", e)
    return []


def append(group_id: str, sender_name: str, content: str):
    """
    追加一条群消息记录

    参数:
        group_id:    群号字符串
        sender_name: 发言者昵称
        content:     消息内容
    """
    cfg = get_config()
    max_lines = cfg.get("memory", {}).get("group_context_lines", 50)

    messages = _load_raw(group_id)
    messages.append({
        "sender_name": sender_name,
        "content": content,
        "timestamp": datetime.now().strftime("%H:%M"),  # 只保留时分，省空间
    })

    # 裁剪到最大条数
    if len(messages) > max_lines:
        messages = messages[-max_lines:]

    _save(group_id, messages)


def get_recent(group_id: str | None) -> list[dict]:
    """
    获取最近的群消息列表

    私聊时 group_id 传 None，直接返回空列表
    返回格式：[{"sender_name": "...", "content": "...", "timestamp": "..."}, ...]
    """
    if not group_id:
        return []
    return _load_raw(group_id)


def _save(group_id: str, messages: list[dict]):
    """把消息列表写回磁盘"""
    path = _ctx_path(group_id)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(messages, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log_error("group_context._save", e)


def clear(group_id: str):
    """清空指定群的上下文（admin 用）"""
    _save(group_id, [])


class GroupContext:
    """群聊上下文类，封装模块级函数，供外部按类方式导入使用"""

    def append(self, group_id: str, sender_name: str, content: str):
        append(group_id, sender_name, content)

    def get_recent(self, group_id: str | None) -> list[dict]:
        return get_recent(group_id)

    def clear(self, group_id: str):
        clear(group_id)
