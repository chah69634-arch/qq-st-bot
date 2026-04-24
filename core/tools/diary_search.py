"""
日记关键词搜索工具
叶瑄可按主题/关键词主动检索历史日记，不限于特定日期
"""
from core.tools.diary_reader import read_recent
from core.error_handler import log_error


async def search_diary_for_user(user_id: str, query: str = "") -> str:
    try:
        text = read_recent(days=30)
        if not text:
            return "最近30天没有找到日记"

        if not query.strip():
            return text[:1000]

        # 关键词提取
        keywords: set = set()
        q = query.strip()
        for length in (2, 3, 4):
            for i in range(len(q) - length + 1):
                chunk = q[i:i+length]
                if chunk.strip():
                    keywords.add(chunk)

        # 按段落匹配
        matched = []
        current_date = ""
        for line in text.splitlines():
            if line.startswith("# "):
                current_date = line.strip("# ").strip()
                continue
            stripped = line.strip()
            if not stripped:
                continue
            if any(kw in stripped for kw in keywords):
                matched.append(f"[{current_date}] {stripped}")

        if not matched:
            return f"日记里没有找到和「{query}」相关的内容"

        selected = matched[:6]
        return "；".join(selected)

    except Exception as e:
        log_error("diary_search.search_diary_for_user", e)
        return "日记检索出错"