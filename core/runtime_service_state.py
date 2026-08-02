"""Lifecycle-owned runtime marker used by offline private-state backups."""
from __future__ import annotations

import json
import os
from pathlib import Path

from core.safe_write import safe_write_json
from core.sandbox import get_paths


def marker_path() -> Path:
    return get_paths().service_state()


def mark_running(*, installation_root: Path) -> None:
    """Publish only process identity; the marker contains no user state or secrets."""
    safe_write_json(
        marker_path(),
        {"pid": os.getpid(), "installation_root": str(installation_root.resolve())},
        keep_bak=False,
    )


def clear_marker() -> None:
    """Remove only this process's marker, leaving another process untouched."""
    path = marker_path()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("pid") == os.getpid():
            path.unlink(missing_ok=True)
    except (OSError, json.JSONDecodeError, TypeError):
        pass
