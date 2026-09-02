"""Strict, non-recursive parser for the RPG character check marker."""

from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class CharacterCheckRequest:
    intent_text: str


@dataclass(frozen=True)
class CharacterMarkerResult:
    visible_text: str
    request: CharacterCheckRequest | None
    status: str


_MARKER = re.compile(r"<C>(.*?)</C>", re.DOTALL)


def parse_character_marker(text: str) -> CharacterMarkerResult:
    if not isinstance(text, str):
        return CharacterMarkerResult("", None, "invalid")
    matches = list(_MARKER.finditer(text))
    if not matches:
        return CharacterMarkerResult(text, None, "absent")
    if len(matches) != 1 or "<C>" in text.replace(matches[0].group(0), "") or "</C>" in text.replace(matches[0].group(0), ""):
        return CharacterMarkerResult(text, None, "invalid")
    body = matches[0].group(1).strip()
    if not 2 <= len(body) <= 120 or "\n" in body or "<" in body or ">" in body:
        return CharacterMarkerResult(text, None, "invalid")
    visible = (text[:matches[0].start()] + text[matches[0].end():]).strip()
    return CharacterMarkerResult(visible, CharacterCheckRequest(body), "valid")
