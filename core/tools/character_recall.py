"""Read-only recall tools for character-authored notes and scoped upload records."""
from __future__ import annotations

from datetime import date
from pathlib import Path

from core.character_document_library import read as read_document_record
from core.character_document_library import search as search_document_records
from core.tools.diary_tool import _parse_date

_NOTE_CAP = 1_500


def _character_diary(char_id: str, target: date) -> str:
    from core.sandbox import get_paths
    path = get_paths().character_inner_diary(char_id=char_id) / f"{target.isoformat()}.md"
    try:
        return path.read_text(encoding="utf-8").strip() if path.is_file() else ""
    except OSError:
        return ""


async def read_character_diary_for_user(user_id: str, char_id: str, date_str: str = "") -> str:
    target = _parse_date(date_str) if date_str else date.today()
    target = target or date.today()
    text = _character_diary(char_id, target)
    if text:
        return f"角色日记 {target.isoformat()}：\n{text[:_NOTE_CAP]}"

    # Preserve the older user-diary capability for installations that have not
    # begun generating character diaries yet; it remains a lower-priority source.
    from core.tools.diary_tool import read_diary_for_user
    legacy = await read_diary_for_user(user_id, date_str=target.isoformat())
    if "还没有日记" not in legacy and "没有可读取" not in legacy:
        return legacy[:_NOTE_CAP]
    return f"没有查到 {target.isoformat()} 的角色日记。"


async def search_character_diary_for_user(user_id: str, char_id: str, query: str = "") -> str:
    from core.sandbox import get_paths
    root = get_paths().character_inner_diary(char_id=char_id)
    terms = [item.casefold() for item in str(query).split() if item.strip()]
    rows: list[str] = []
    if root.exists():
        for path in sorted(root.glob("*.md"), reverse=True):
            try:
                text = path.read_text(encoding="utf-8").strip()
            except OSError:
                continue
            if not text:
                continue
            if terms and not all(term in text.casefold() for term in terms):
                continue
            excerpt = " ".join(text.split())[:260]
            rows.append(f"[{path.stem}] {excerpt}")
            if len(rows) >= 6:
                break
    if rows:
        return "角色日记检索结果：\n" + "\n".join(rows)
    return f"角色日记里没有找到和「{query}」相关的内容。" if query.strip() else "还没有可检索的角色日记。"


async def search_documents_for_user(user_id: str, char_id: str, query: str = "", media_type: str = "") -> str:
    rows = search_document_records(user_id, char_id, query, media_type=media_type)
    if not rows:
        return "没有查到相关资料。"
    lines = []
    for row in rows:
        lines.append(
            f"{row['document_id']} | {row['filename']} | {row['media_type']} | {row['created_at'][:10]}\n摘要：{row['summary']}"
        )
    return "资料检索结果：\n" + "\n".join(lines)


async def read_document_for_user(user_id: str, char_id: str, document_id: str, offset: int = 0) -> str:
    row = read_document_record(user_id, char_id, document_id, offset=offset)
    if row is None:
        return "没有查到这份资料。"
    more = f" 可继续从 offset={row['next_offset']} 读取。" if row["next_offset"] is not None else ""
    return f"资料《{row['filename']}》：\n{row['content']}{more}"


async def search_character_notes_for_user(user_id: str, char_id: str, query: str = "") -> str:
    """Search character-authored diary entries in the active scope."""
    results: list[str] = []
    diary = await search_character_diary_for_user(user_id, char_id, query)
    if not diary.startswith("角色日记里没有") and not diary.startswith("还没有"):
        results.append(diary)
    return "\n".join(results)[:_NOTE_CAP] if results else "没有查到相关角色手记。"
