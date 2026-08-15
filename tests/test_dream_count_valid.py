from tests.fixtures.public_assets import TEST_CHAR_ID
"""
tests/test_dream_count_valid.py — count_valid_dreams() unit tests

Verifies:
  - 1 valid dream (4 user turns) + 1 short dream (2 user turns) → total_valid=1, total_archived=2
  - All dreams below threshold → total_valid=0
  - Empty archive dir → all zeros
  - No archive dir → all zeros
  - last_dream_at reflects the highest ts across valid dreams only
  - Corrupt lines are skipped, file still counted if enough valid user lines remain
"""

import json
import time
from pathlib import Path

import pytest


def _write_dream(archive_dir: Path, dream_id: str, turns: list[dict]) -> Path:
    f = archive_dir / f"dream_{dream_id}.jsonl"
    archive_dir.mkdir(parents=True, exist_ok=True)
    lines = []
    for t in turns:
        lines.append(json.dumps(t))
    f.write_text("\n".join(lines), encoding="utf-8")
    return f


def _user_turn(ts: float) -> dict:
    return {"role": "user", "content": "hi", "ts": ts}


def _assistant_turn(ts: float) -> dict:
    return {"role": "assistant", "content": "reply", "ts": ts}


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def archive(sandbox):
    """Return the v1 archive dir for char_id=yexuan (created on demand)."""
    from core.sandbox import get_paths
    d = get_paths().dreams_archive_dir(char_id=TEST_CHAR_ID)
    d.mkdir(parents=True, exist_ok=True)
    return d


# ── tests ─────────────────────────────────────────────────────────────────────

def test_one_valid_one_short(archive):
    """4-turn dream counts; 2-turn dream does not."""
    base = 1_700_000_000.0
    _write_dream(archive, "aaa", [
        _user_turn(base + 1),
        _assistant_turn(base + 2),
        _user_turn(base + 3),
        _assistant_turn(base + 4),
        _user_turn(base + 5),
        _assistant_turn(base + 6),
        _user_turn(base + 7),  # 4th user turn → valid
    ])
    _write_dream(archive, "bbb", [
        _user_turn(base + 10),
        _assistant_turn(base + 11),
        _user_turn(base + 12),  # 2 user turns → not valid
    ])

    from core.dream.dream_log import count_valid_dreams
    result = count_valid_dreams(char_id=TEST_CHAR_ID)

    assert result["total_archived"] == 2
    assert result["total_valid"] == 1
    assert result["last_dream_at"] == pytest.approx(base + 7)


def test_all_short_dreams(archive):
    """All dreams under threshold → total_valid=0."""
    base = 1_700_000_000.0
    for dream_id in ("x1", "x2"):
        _write_dream(archive, dream_id, [
            _user_turn(base),
            _assistant_turn(base + 1),
            _user_turn(base + 2),  # 2 turns
        ])

    from core.dream.dream_log import count_valid_dreams
    result = count_valid_dreams(char_id=TEST_CHAR_ID)

    assert result["total_archived"] == 2
    assert result["total_valid"] == 0
    assert result["last_dream_at"] is None


def test_empty_archive_dir(archive):
    """Archive dir exists but is empty."""
    from core.dream.dream_log import count_valid_dreams
    result = count_valid_dreams(char_id=TEST_CHAR_ID)

    assert result == {"total_valid": 0, "total_archived": 0, "last_dream_at": None}


def test_no_archive_dir(sandbox):
    """Archive dir does not exist at all → zeros, no crash."""
    from core.dream.dream_log import count_valid_dreams
    result = count_valid_dreams(char_id=TEST_CHAR_ID)

    assert result == {"total_valid": 0, "total_archived": 0, "last_dream_at": None}


def test_corrupt_lines_skipped(archive):
    """Corrupt JSON lines in a file are skipped; valid user turns still counted."""
    base = 1_700_000_000.0
    f = archive / "dream_corrupt.jsonl"
    lines = [
        json.dumps(_user_turn(base + i)) for i in range(4)  # 4 valid user turns
    ] + ["not-json-at-all", "{broken"]
    f.write_text("\n".join(lines), encoding="utf-8")

    from core.dream.dream_log import count_valid_dreams
    result = count_valid_dreams(char_id=TEST_CHAR_ID)

    assert result["total_valid"] == 1
    assert result["total_archived"] == 1


def test_last_dream_at_is_max_ts_across_valid(archive):
    """last_dream_at picks the highest ts among valid dreams."""
    base = 1_700_000_000.0
    # valid dream with earlier ts
    _write_dream(archive, "early", [_user_turn(base + i) for i in range(4)])
    # valid dream with later ts
    _write_dream(archive, "late", [_user_turn(base + 100 + i) for i in range(4)])

    from core.dream.dream_log import count_valid_dreams
    result = count_valid_dreams(char_id=TEST_CHAR_ID)

    assert result["total_valid"] == 2
    assert result["last_dream_at"] == pytest.approx(base + 103)
