"""Write-once RPG player replay archive."""

from __future__ import annotations

import json
import time
from typing import Any

from core.dream import rpg_store
from core.safe_write import safe_write_json, safe_write_text


def archive_session(uid: str, dream_id: str, *, char_id: str) -> tuple[bool, str]:
    target = rpg_store.archive_path(uid, dream_id, char_id=char_id)
    metadata_path = rpg_store.archive_metadata_path(uid, dream_id, char_id=char_id)
    if target.exists() and metadata_path.exists():
        return True, "already_archived"
    rows, partial = rpg_store.read_transcript(uid, dream_id, char_id=char_id)
    core, _health = rpg_store.load(uid, dream_id, char_id=char_id)
    if partial:
        return False, "transcript_invalid"
    try:
        text = "".join(json.dumps({key: row.get(key) for key in ("entry_id", "lane", "kind", "content", "ts", "correlation_id")}, ensure_ascii=False, separators=(",", ":")) + "\n" for row in rows)
        if not safe_write_text(target, text):
            return False, "archive_write_failed"
        metadata = {"schema_version": 1, "dream_id": dream_id, "char_id": char_id, "archived_at": time.time(), "entry_count": len(rows), "scene_revision": core.scene_revision if core else 0, "active_branch_id": core.active_branch_id if core else "root"}
        if not safe_write_json(metadata_path, metadata):
            return False, "metadata_write_failed"
    except Exception:
        return False, "archive_write_failed"
    return True, "archived"


def read_archive(uid: str, dream_id: str, *, char_id: str) -> tuple[list[dict[str, Any]], dict[str, Any], bool]:
    rows, partial = rpg_store.read_jsonl_with_health(rpg_store.archive_path(uid, dream_id, char_id=char_id))
    try:
        metadata = json.loads(rpg_store.archive_metadata_path(uid, dream_id, char_id=char_id).read_text(encoding="utf-8"))
    except Exception:
        metadata = {}
    return rows, metadata if isinstance(metadata, dict) else {}, partial
