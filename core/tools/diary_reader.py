"""
日记读取模块
读取 E:\\obsidian_note\\Psychology 下的日记和心理感悟
"""
from pathlib import Path
from datetime import date, timedelta
from core.error_handler import log_error

DIARY_ROOT = Path(r"E:\obsidian_note\Psychology")

def read_diary(target_date: date) -> str:
    """读取指定日期的日记，返回文本，不存在返回空字符串"""
    filename = f"{target_date.strftime('%Y-%m-%d')}.md"
    for path in DIARY_ROOT.rglob(filename):
        try:
            return path.read_text(encoding="utf-8").strip()
        except Exception as e:
            from core.error_handler import log_error
            log_error("diary_reader.read_diary", e)
    return ""

def read_recent(days: int = 3) -> str:
    """读取最近N天的所有md文件，拼接返回"""
    today = date.today()
    parts = []
    for i in range(1, days + 1):
        target = today - timedelta(days=i)
        text = read_diary(target)
        if text:
            parts.append(f"# {target}\n{text}")
    return "\n\n".join(parts)

def yesterday_missing() -> bool:
    """昨天是否没有日记"""
    yesterday = date.today() - timedelta(days=1)
    return read_diary(yesterday) == ""
