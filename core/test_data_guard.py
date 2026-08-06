"""Test-data identity detection and production runtime audit helpers."""

from __future__ import annotations

import re
from pathlib import Path

_HIGH_CONFIDENCE_TEST_ID = re.compile(
    r"^(?:pytest(?:[_-].*)?|"
    r"test_(?:uid|user|session|worker|char)(?:[_-].*)?|"
    r"uid_[a-z0-9_]+_test)$",
    re.IGNORECASE,
)


def is_test_identifier(value: object) -> bool:
    """Return whether *value* is an unambiguous test UID/session marker."""
    normalized = str(value).strip()
    return bool(normalized and _HIGH_CONFIDENCE_TEST_ID.fullmatch(normalized))


def assert_production_identity_allowed(*values: object, mode: str) -> None:
    """Reject high-confidence test identities when resolving production paths."""
    if str(mode).strip().lower() != "production":
        return
    blocked = [str(value) for value in values if is_test_identifier(value)]
    if blocked:
        raise RuntimeError(
            "production runtime cannot write test identity: " + ", ".join(blocked)
        )


def classify_test_directories(
    root: Path,
    *,
    char_id: str | None = None,
) -> list[dict[str, str]]:
    """Read-only classification of obvious test UID directories."""
    findings: list[dict[str, str]] = []
    if not root.is_dir():
        return findings
    char_dirs = [(char_id, root)] if char_id is not None else [
        (item.name, item)
        for item in sorted(
            (entry for entry in root.iterdir() if entry.is_dir()),
            key=lambda path: path.name,
        )
    ]
    for resolved_char_id, char_dir in char_dirs:
        uid_dirs = sorted(
            (item for item in char_dir.iterdir() if item.is_dir()),
            key=lambda path: path.name,
        )
        for uid_dir in uid_dirs:
            if is_test_identifier(uid_dir.name):
                findings.append(
                    {
                        "char_id": str(resolved_char_id),
                        "user_id": uid_dir.name,
                        "path": str(uid_dir),
                    }
                )
    return findings
