"""Shared source policy for legacy Markdown event-log blocks."""
from __future__ import annotations

import re
from typing import Iterable

from core.memory.source_policy import ISOLATED_SOURCES

_SOURCE_RE = re.compile(r"\bsource:([^\s]+)")


def split_blocks(text: str) -> list[list[str]]:
    blocks: list[list[str]] = []
    current: list[str] = []
    for line in text.splitlines():
        if line.startswith("## "):
            if current:
                blocks.append(current)
            current = [line]
        elif current or line.strip():
            current.append(line)
    if current:
        blocks.append(current)
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
