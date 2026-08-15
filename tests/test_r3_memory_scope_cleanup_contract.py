"""
tests/test_r3_memory_scope_cleanup_contract.py
==============================================
R3 cleanup contract: verifies that allowlisted migration-target files still
have violations and tracks cleanup progress.

This test complements test_r3_scope_lint.py (which gates NEW violations) by
verifying that EXISTING allowlist entries still have violations — i.e., when a
file is cleaned up, this test fails, signalling the developer to remove that
entry from the allowlist in test_r3_scope_lint.py.

  test_r3_scope_lint.py              — gates NEW violations (fails when new bad code
                                       is added outside allowlists)
  test_r3_memory_scope_cleanup_contract.py — gates STALE ALLOWLIST ENTRIES (fails when
                                             an existing violation is fixed but the
                                             allowlist entry is not removed)

Together they keep both allowlists self-maintaining.

Allowlist categories:
  _FOREVER  — files where the default is correct by design; will never be cleaned.
  _MIGRATION_TARGETS — files with known violations scheduled for future cleanup.
"""
from __future__ import annotations
from tests.fixtures.public_assets import TEST_CHAR_ID

from pathlib import Path

from tests.test_r3_scope_lint import (
    CHAR_ID_DEFAULT_ALLOWLIST,
    DATA_PATH_ALLOWLIST,
    _find_yexuan_defaults,
    _find_bare_data_paths,
    PROJECT_ROOT,
)

# ---------------------------------------------------------------------------
# Categorised char_id allowlist
# ---------------------------------------------------------------------------

# Files whose char_id=TEST_CHAR_ID defaults are correct BY DESIGN and will not be
# removed — they are the canonical path authority or intentional compat layers.
_CHAR_ID_FOREVER: frozenset[str] = frozenset({
    "core/data_paths.py",  # canonical path authority — char_id defaults are by design
})

# All remaining allowlisted files are MIGRATION TARGETS: violations exist today
# but are scheduled for cleanup.  When a file is cleaned up, this test will fail
# with a message to remove it from CHAR_ID_DEFAULT_ALLOWLIST.
_CHAR_ID_MIGRATION_TARGETS: frozenset[str] = CHAR_ID_DEFAULT_ALLOWLIST - _CHAR_ID_FOREVER

# ---------------------------------------------------------------------------
# Categorised data-path allowlist
# ---------------------------------------------------------------------------

_DATA_PATH_FOREVER: frozenset[str] = frozenset({
    "core/data_paths.py",         # canonical path authority — by design
})

_DATA_PATH_MIGRATION_TARGETS: frozenset[str] = DATA_PATH_ALLOWLIST - _DATA_PATH_FOREVER

# ---------------------------------------------------------------------------
# Contract: migration-target files must still have violations
# ---------------------------------------------------------------------------

def test_char_id_migration_targets_still_have_violations():
    """
    Each MIGRATION_TARGET must still contain char_id=TEST_CHAR_ID function defaults.
    When this test fails for file X, X has been cleaned up — remove it from
    CHAR_ID_DEFAULT_ALLOWLIST in test_r3_scope_lint.py.
    """
    already_clean: list[str] = []

    for rel in sorted(_CHAR_ID_MIGRATION_TARGETS):
        path = PROJECT_ROOT / rel
        if not path.exists():
            continue  # stale file — test_allowlisted_files_still_exist in scope_lint catches this
        hits = _find_yexuan_defaults(path.read_text(encoding="utf-8"))
        if not hits:
            already_clean.append(rel)

    assert not already_clean, (
        "These migration-target files no longer have char_id=TEST_CHAR_ID defaults.\n"
        "Please remove them from CHAR_ID_DEFAULT_ALLOWLIST in tests/test_r3_scope_lint.py:\n"
        + "\n".join(f"  {f}" for f in already_clean)
    )


def test_data_path_migration_targets_still_have_violations():
    """
    Each DATA_PATH migration target must still contain bare data/ path constructions.
    When this test fails for file X, X has been cleaned up — remove it from
    DATA_PATH_ALLOWLIST in test_r3_scope_lint.py.
    """
    already_clean: list[str] = []

    for rel in sorted(_DATA_PATH_MIGRATION_TARGETS):
        path = PROJECT_ROOT / rel
        if not path.exists():
            continue
        hits = _find_bare_data_paths(path.read_text(encoding="utf-8"))
        if not hits:
            already_clean.append(rel)

    assert not already_clean, (
        "These migration-target files no longer have bare data/ path constructions.\n"
        "Please remove them from DATA_PATH_ALLOWLIST in tests/test_r3_scope_lint.py:\n"
        + "\n".join(f"  {f}" for f in already_clean)
    )


# ---------------------------------------------------------------------------
# Admin routes: no char_id=TEST_CHAR_ID function-parameter defaults
# ---------------------------------------------------------------------------

_ADMIN_ROOT = PROJECT_ROOT / "admin"


def test_admin_no_char_id_defaults():
    """
    No file under admin/ may define char_id=TEST_CHAR_ID as a function-parameter default.
    Admin routes must resolve char_id from active_prompt_assets or require explicit
    caller input; they must never silently fallback to a hardcoded character.
    """
    violations: dict[str, list[int]] = {}

    for path in _ADMIN_ROOT.rglob("*.py"):
        rel = path.relative_to(PROJECT_ROOT).as_posix()
        hits = _find_yexuan_defaults(path.read_text(encoding="utf-8"))
        if hits:
            violations[rel] = hits

    assert not violations, (
        "char_id=TEST_CHAR_ID function defaults found in admin/.\n"
        "Admin routes must resolve char_id from active_prompt_assets or require it "
        "as an explicit query parameter.\n"
        f"Violations: {violations}"
    )


# ---------------------------------------------------------------------------
# Negative tests: ensure the detectors are not over-eager
# ---------------------------------------------------------------------------

def test_detector_does_not_flag_test_fixture_call_kwarg():
    """Call-site char_id=TEST_CHAR_ID kwargs in test fixtures must not be flagged."""
    src = """\
def test_isolation(sandbox):
    s1 = _make_session(sandbox, uid="user1", char_id=TEST_CHAR_ID)
    s2 = _make_session(sandbox, uid="user2", char_id=TEST_CHAR_ID)
    assert s1 != s2
"""
    assert _find_yexuan_defaults(src) == [], (
        "Detector must not flag call-site kwargs — only function-parameter defaults"
    )


def test_detector_does_not_flag_comment_or_docstring_data_path():
    """data/ references inside comments and docstrings must not be flagged."""
    src = """\
\"\"\"
S6 layout: data/runtime/memory/{char_id}/{uid}/history.json
\"\"\"
# Old path: data/history/{uid}.json was the pre-S6 layout.
def load(uid: str) -> list:
    return []
"""
    assert _find_bare_data_paths(src) == [], (
        "Detector must not flag data/ references inside docstrings or comments"
    )


def test_detector_does_not_flag_test_files_for_data_path():
    """Test files that reference data/ in string literals (for path assertions) are not core/."""
    # Simulate a test that asserts a path contains "data/runtime/..."
    src = """\
def test_path_shape(sandbox):
    p = sandbox.user_memory_root("uid1", char_id=TEST_CHAR_ID)
    assert "data/runtime/memory" in str(p)
"""
    # The detector would flag this if the file were in core/ (it contains "data/" in a string),
    # but test files are not scanned by _iter_core_py so they're already excluded.
    # This test confirms the detector WOULD fire — the exclusion is at the iterator level.
    hits = _find_bare_data_paths(src)
    # The string `"data/runtime/memory"` contains `data/` but is NOT a Path(...) or f-string or concat.
    # Our regex only matches: Path("data/..."), f"data/..., or "data/" + ...
    # A plain string like "data/runtime/memory" in str(p) is NOT matched.
    assert hits == [], "Assertion-style data/ string literals must not be flagged"
