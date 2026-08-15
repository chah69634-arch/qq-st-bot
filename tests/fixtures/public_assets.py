"""Stable public asset ids and installation helpers for isolated tests.

The test suite must not depend on a developer's ignored ``userdata/`` tree.
These ids intentionally have no relationship with any deployment role names.
"""

from __future__ import annotations

import shutil
from pathlib import Path


TEST_CHAR_ID = "fixture_character"
TEST_PEER_CHAR_ID = "fixture_peer"
TEST_THIRD_CHAR_ID = "fixture_third"
TEST_CHAR_IDS = (TEST_CHAR_ID, TEST_PEER_CHAR_ID, TEST_THIRD_CHAR_ID)
TEST_CHAR_NAME = "Fixture Companion"

_FIXTURE_ROOT = Path(__file__).parent
PUBLIC_CHARACTER_CARDS = _FIXTURE_ROOT / "characters" / "cards"
PUBLIC_DREAM_WORLDS = _FIXTURE_ROOT / "dream_worlds"


def install_public_character_cards(paths) -> tuple[str, ...]:
    """Install tracked public role cards into the active test sandbox."""
    for char_id in TEST_CHAR_IDS:
        source = PUBLIC_CHARACTER_CARDS / f"{char_id}.json"
        target = paths.character_card_write_path(char_id)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    return TEST_CHAR_IDS


def install_public_dream_worlds(target: Path) -> Path:
    """Copy the tracked public dream-world package into a test sandbox."""
    target = Path(target)
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(PUBLIC_DREAM_WORLDS, target)
    return target
