from datetime import date, datetime
from core.tools.diary_reader import read_diary


def _parse_date(date_str: str) -> date | None:
    """解析多种日期格式，失败返回 None"""
    s = date_str.strip()
    today = date.today()
    year = today.year
    for fmt, src in [
        ("%Y-%m-%d", s),
        ("%m-%d",    s),
        ("%m月%d日", s),
    ]:
        try:
            d = datetime.strptime(src, fmt).date()
            if fmt != "%Y-%m-%d":
                d = d.replace(year=year)
            return d
        except ValueError:
            pass
    # 纯数字 0410
    if s.isdigit() and len(s) == 4:
        try:
            return date(year, int(s[:2]), int(s[2:]))
        except ValueError:
            pass
    return None


async def read_diary_for_user(user_id: str, date_str: str = "") -> str:
    target = _parse_date(date_str) if date_str else date.today()
    if target is None:
        target = date.today()

    text = read_diary(target)
    if text:
        try:
            from core.scheduler import mark_diary_shared
            mark_diary_shared()
        except Exception:
            pass
        date_label = target.strftime("%m月%d日")
        return f"她{date_label}的日记内容：\n{text}"
    date_label = target.strftime("%m月%d日")
    return f"{date_label}还没有日记"
