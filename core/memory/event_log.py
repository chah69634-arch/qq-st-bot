"""
不可变事件日志系统
─────────────────────────────────────────────────────
每次对话结束后，把"用户说了什么、叶瑄回了什么"追加到
按天分割的 Markdown 日志文件里，永不修改已写内容。

存储结构：
  data/event_log/{user_id}/2026-04-15.md   ← AI 读取（按天）
  data/event_log/{user_id}/full_log.md     ← 供用户导出，AI 不读

日志格式（每次对话块）：
  ## 14:23
  **用户**：我今天很累
  **叶瑄**：（走过来把外套搭在你肩上）先坐着
  ---
"""

import logging
from datetime import datetime, timedelta
from pathlib import Path

from core.error_handler import log_error

logger = logging.getLogger(__name__)

# 日志根目录
_LOG_ROOT = Path("data/event_log")


def _day_file(user_id: str, date: datetime) -> Path:
    """返回指定用户、指定日期的日志文件路径"""
    return _LOG_ROOT / user_id / f"{date.strftime('%Y-%m-%d')}.md"


def _full_log_file(user_id: str) -> Path:
    """返回用户的完整导出日志路径"""
    return _LOG_ROOT / user_id / "full_log.md"


def _ensure_dir(user_id: str):
    """确保用户日志目录存在"""
    (_LOG_ROOT / user_id).mkdir(parents=True, exist_ok=True)


def append(user_id: str, role: str, content: str):
    """
    追加一条对话记录到当天日志和 full_log.md。
    永不修改已有内容，只追加。

    参数：
        user_id  - 用户 QQ 号
        role     - "user" 或 "assistant"
        content  - 消息内容
    """
    # 把 role 映射成中文显示名
    role_label = "用户" if role == "user" else "叶瑄"

    now = datetime.now()
    time_str = now.strftime("%H:%M")

    # 一条"块"开头用时间戳，后续同一轮追加行
    # 格式：**用户**：xxx  或  **叶瑄**：xxx
    line = f"**{role_label}**：{content}\n"

    # 如果是 user 说话，在前面加时间戳小标题 + 空行
    header = f"\n## {time_str}\n" if role == "user" else ""
    # assistant 说完加分隔线
    footer = "---\n" if role == "assistant" else ""

    chunk = header + line + footer

    try:
        _ensure_dir(user_id)

        # 写入当天日期文件
        day_path = _day_file(user_id, now)
        with open(day_path, "a", encoding="utf-8") as f:
            f.write(chunk)

        # 同时写入 full_log.md（供用户导出，AI 不读取）
        full_path = _full_log_file(user_id)
        with open(full_path, "a", encoding="utf-8") as f:
            f.write(chunk)

    except Exception as e:
        log_error("event_log.append", e)


def get_recent_days(user_id: str, days: int = 3) -> str:
    """
    读取最近 N 天的日志原文，拼接成一个字符串返回。
    只读按天分割的文件，不读 full_log.md。
    如果某天没有日志就跳过，不报错。

    参数：
        user_id - 用户 QQ 号
        days    - 往前读几天（含今天），默认 3

    返回：
        拼接后的日志文本，空则返回空字符串
    """
    parts = []
    today = datetime.now()

    for i in range(days):
        target_day = today - timedelta(days=i)
        path = _day_file(user_id, target_day)
        try:
            if path.exists():
                text = path.read_text(encoding="utf-8").strip()
                if text:
                    # 加日期头，方便 LLM 理解时间顺序
                    parts.append(f"# {target_day.strftime('%Y-%m-%d')}\n{text}")
        except Exception as e:
            log_error("event_log.get_recent_days", e)

    # 按时间正序（最早在前）返回
    parts.reverse()
    return "\n\n".join(parts)


async def search(user_id: str, query: str, llm_client=None) -> str:
    """
    在最近3天的日志里关键词匹配与 query 相关的内容。
    将 query 按空白分词，逐行扫描，返回最多3条命中行。
    没有相关内容返回空字符串。

    参数：
        user_id    - 用户 QQ 号
        query      - 当前用户消息（用来做关键词匹配）
        llm_client - 保留参数，不再使用

    返回：
        命中的日志行（最多3条，分号连接），无匹配返回 ""
    """
    recent_text = get_recent_days(user_id, days=3)
    if not recent_text:
        return ""

    # 按空白分词，过滤长度 <= 1 的片段
    keywords = [w.strip() for w in query.split() if len(w.strip()) > 1]
    if not keywords:
        return ""

    matched: list[str] = []
    for line in recent_text.splitlines():
        stripped = line.strip()
        # 跳过标题行、分隔线、空行
        if not stripped or stripped.startswith("#") or stripped == "---":
            continue
        if any(kw in stripped for kw in keywords):
            matched.append(stripped)
            if len(matched) >= 3:
                break

    return "；".join(matched) if matched else ""


class EventLog:
    """
    EventLog 类封装，供外部按类方式导入使用。
    所有方法都代理到模块级函数。
    """

    def append(self, user_id: str, role: str, content: str):
        append(user_id, role, content)

    def get_recent_days(self, user_id: str, days: int = 3) -> str:
        return get_recent_days(user_id, days)

    async def search(self, user_id: str, query: str, llm_client=None) -> str:
        return await search(user_id, query, llm_client)
