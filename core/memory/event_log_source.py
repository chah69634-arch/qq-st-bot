"""Shared source policy for legacy Markdown event-log blocks."""
from __future__ import annotations

import re
from typing import Iterable

from core.memory.source_policy import ISOLATED_SOURCES

_SOURCE_RE = re.compile(r"\bsource:([^\s]+)")
_DATE_HEADER_RE = re.compile(r"^# \d{4}-\d{2}-\d{2}\s*$")


def split_blocks(text: str) -> list[list[str]]:
    blocks: list[list[str]] = []
    current: list[str] = []
    date_header = ""

    def flush() -> None:
        nonlocal current
        if current and any(line.strip() != date_header for line in current):
            blocks.append(current)
        current = []

    for line in text.splitlines():
        if _DATE_HEADER_RE.fullmatch(line):
            flush()
            date_header = line
        elif line.startswith("## "):
            flush()
            current = [date_header, line] if date_header else [line]
        elif current or line.strip():
            if not current and date_header:
                current = [date_header]
            current.append(line)
    flush()
    return blocks


def block_sources(lines: Iterable[str]) -> set[str]:
    return {
        match.group(1).strip()
        for line in lines
        if line.lstrip().startswith(">")
        for match in _SOURCE_RE.finditer(line)
        if match.group(1).strip()
    }


def block_is_recallable(lines: Iterable[str]) -> bool:
    """Empty source stays compatible; only explicit ordinary migration is visible."""
    sources = block_sources(lines)
    if not sources:
        return True
    return all(source == "legacy_migration" and source not in ISOLATED_SOURCES for source in sources)


def filter_recallable_text(text: str) -> tuple[str, int]:
    kept: list[str] = []
    skipped = 0
    for block in split_blocks(text):
        if block_is_recallable(block):
            kept.append("\n".join(block))
        else:
            skipped += 1
    return "\n".join(kept), skipped
