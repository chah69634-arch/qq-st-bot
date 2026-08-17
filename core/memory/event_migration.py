"""Offline, resumable import of legacy Markdown conversation evidence.

This module never participates in the chat path.  It reads legacy sources,
creates deterministic ledger events in bounded batches, and records only
content-free import progress.  A malformed legacy block becomes a
``legacy_unknown`` reference instead of an inferred conversation event.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from core.memory import event_store
from core.memory.path_resolver import resolve_path
from core.memory.scope import MemoryScope
from core.safe_write import safe_write_json
from core.sandbox import get_paths, safe_user_id

_DAY_FILE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}\.md$")
_TIME_RE = re.compile(r"^##\s+(\d{2}:\d{2})\s*$")
_MESSAGE_RE = re.compile(r"^\*\*([^*]+)\*\*[：:](.*)$")
_SPEAKER_RE = re.compile(r"\bspeaker:(user|assistant)\b")
_LEGACY_ARTIFACTS = (
    ("short_term", "history", "history"),
    ("mid_term", "mid_term", "mid_term"),
    ("episodic", "episodic_memory", "episodic"),
    ("storyline", "storyline", "storyline"),
)


@dataclass(frozen=True)
class MigrationEntry:
    event_id: str
    legacy_ref: str
    block_hash: str
    occurred_at: float
    kind: str
    actor: str
    text: str = ""

    def event(self) -> dict[str, Any]:
        unknown = self.kind == "legacy_unknown"
        reference = f"[legacy_unknown:{self.legacy_ref}]"
        return {
            "event_id": self.event_id,
            "turn_id": f"legacy:{self.block_hash[:24]}",
            "seq": 0,
            "occurred_at": self.occurred_at,
            "ingested_at": time.time(),
            "realm": "reality",
            "kind": self.kind,
            "actor": self.actor,
            "channel": "legacy_markdown",
            "stream": "legacy_markdown",
            "source": "legacy_migration",
            # The original Markdown remains in place.  The ledger stores a
            # stable reference and hash, not a second raw copy for unknowns.
            "raw_payload_json": {
                "legacy_ref": self.legacy_ref,
                "legacy_block_sha256": self.block_hash,
                "legacy_unknown": unknown,
            },
            "raw_text": "" if unknown else self.text,
            "visible_text": reference if unknown else self.text,
            "memory_text": reference if unknown else self.text,
            "media_refs_json": [],
        }


def legacy_event_log_dir(scope: MemoryScope) -> Path:
    """Return only the old uid-only Markdown location for import."""
    return get_paths()._p("event_log") / safe_user_id(scope.uid)


def _state_path(scope: MemoryScope) -> Path:
    return resolve_path(scope, "event_migration_state")


def read_state(scope: MemoryScope) -> dict[str, Any]:
    path = _state_path(scope)
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}


def migration_status(scope: MemoryScope) -> dict[str, Any]:
    """Content-free admin projection of persisted import progress."""
    state = read_state(scope)
    allowed = {
        "state_version", "status", "source_digest", "total", "next_offset",
        "parsed", "malformed", "legacy_unknown", "duplicate", "conflict",
        "written", "failed", "backup", "updated_at", "last_error",
    }
    return {key: state[key] for key in allowed if key in state}


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _date_time(path: Path, time_text: str | None) -> float | None:
    if time_text is None:
        return None
    try:
        return datetime.strptime(f"{path.stem} {time_text}", "%Y-%m-%d %H:%M").timestamp()
    except ValueError:
        return None


def _block_entries(path: Path, text: str) -> tuple[list[MigrationEntry], int, int]:
    entries: list[MigrationEntry] = []
    parsed = malformed = 0
    blocks: list[list[str]] = []
    current: list[str] = []
    for line in text.splitlines():
        if line.startswith("## "):
            if current:
                blocks.append(current)
            current = [line]
        elif current:
            current.append(line)
        elif line.strip():
            blocks.append([line])
    if current:
        blocks.append(current)

    for block in blocks:
        raw_block = "\n".join(block).strip()
        if not raw_block:
            continue
        block_hash = _sha(raw_block)
        legacy_ref = f"{path.name}#{block_hash[:16]}"
        time_match = _TIME_RE.match(block[0]) if block else None
        occurred_at = _date_time(path, time_match.group(1) if time_match else None)
        speaker = ""
        for line in block:
            match = _SPEAKER_RE.search(line)
            if match:
                speaker = match.group(1)
                break
        message_indices = [index for index, line in enumerate(block) if _MESSAGE_RE.match(line)]
        emitted = 0
        for position, index in enumerate(message_indices):
            match = _MESSAGE_RE.match(block[index])
            assert match is not None
            label, first_text = match.groups()
            # A legacy label can be a character display name, but cannot prove
            # which actor it denotes.  Only the stable user label or matching
            # speaker metadata is admitted; contradictory fake metadata stays
            # a legacy_unknown reference.
            if label.strip() == "用户":
                actor = "user" if speaker in {"", "user"} else ""
            else:
                actor = "assistant" if speaker == "assistant" else ""
            if actor not in {"user", "assistant"} or occurred_at is None:
                continue
            next_index = message_indices[position + 1] if position + 1 < len(message_indices) else len(block)
            continuations = [
                line.strip() for line in block[index + 1:next_index]
                if line.strip() and not line.lstrip().startswith(">") and line.strip() != "---"
            ]
            body = "\n".join([first_text.strip(), *continuations]).strip()
            if not body:
                continue
            event_id = f"legacy-{_sha(f'{legacy_ref}:{index}')[:40]}"
            entries.append(MigrationEntry(event_id, legacy_ref, block_hash, occurred_at, "legacy_message", actor, body))
            emitted += 1
            parsed += 1
        if emitted == 0:
            # Import time is explicitly not a claim about original occurrence.
            # The original actor/time/causality remain unknown in the retained MD.
            event_id = f"legacy-{_sha(f'{legacy_ref}:unknown')[:40]}"
            entries.append(MigrationEntry(event_id, legacy_ref, block_hash, time.time(), "legacy_unknown", "legacy_unknown"))
            malformed += 1
    return entries, parsed, malformed


def _json_item_count(path: Path) -> tuple[int, int]:
    if not path.exists():
        return 0, 0
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return 0, 1
    if isinstance(value, list):
        return len(value), 0
    if isinstance(value, dict):
        return len(value.get("entries") or value.get("events") or value.get("arcs") or value), 0
    return 0, 1


def scan_legacy(scope: MemoryScope, *, source_dir: Path | None = None) -> dict[str, Any]:
    """Read all requested legacy stores and return a content-free plan."""
    if scope.domain != "reality":
        raise ValueError("event migration requires a reality scope")
    directory = Path(source_dir) if source_dir is not None else legacy_event_log_dir(scope)
    entries: list[MigrationEntry] = []
    parsed = malformed = 0
    source_digests: list[str] = []
    if directory.is_dir():
        for path in sorted(directory.iterdir(), key=lambda item: item.name):
            if not path.is_file() or not _DAY_FILE_RE.fullmatch(path.name):
                continue
            try:
                content = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                malformed += 1
                continue
            source_digests.append(f"{path.name}:{_sha(content)}")
            file_entries, file_parsed, file_malformed = _block_entries(path, content)
            entries.extend(file_entries)
            parsed += file_parsed
            malformed += file_malformed
    artifacts: dict[str, dict[str, int | bool]] = {}
    for name, legacy_dir, resolver_key in _LEGACY_ARTIFACTS:
        legacy_path = get_paths()._p(legacy_dir, f"{safe_user_id(scope.uid)}.json")
        current_path = resolve_path(scope, resolver_key)
        source_path = legacy_path if legacy_path.exists() else current_path
        count, invalid = _json_item_count(source_path)
        artifacts[name] = {"present": source_path.exists(), "items": count, "malformed": invalid}
    return {
        "entries": entries,
        "total": len(entries),
        "parsed": parsed,
        "malformed": malformed,
        "legacy_unknown": malformed,
        "duplicate": 0,
        "conflict": 0,
        "source_digest": _sha("\n".join(source_digests)),
        "artifacts": artifacts,
    }


def apply_batch(
    scope: MemoryScope,
    plan: dict[str, Any],
    *,
    batch_size: int,
    backup: dict[str, Any],
) -> dict[str, Any]:
    """Append at most one deterministic batch and persist resumable progress."""
    if batch_size < 1 or batch_size > 100:
        raise ValueError("batch_size must be between 1 and 100")
    if backup.get("verified") is not True:
        raise ValueError("backup_not_verified")
    entries = list(plan["entries"])
    previous = read_state(scope)
    same_source = previous.get("source_digest") == plan["source_digest"]
    start = int(previous.get("next_offset", 0)) if same_source else 0
    start = max(0, min(start, len(entries)))
    state: dict[str, Any] = {
        "state_version": 1,
        "status": "running",
        "source_digest": plan["source_digest"],
        "total": len(entries),
        "next_offset": start,
        "parsed": int(plan["parsed"]),
        "malformed": int(plan["malformed"]),
        "legacy_unknown": int(plan["legacy_unknown"]),
        "duplicate": int(previous.get("duplicate", 0)) if same_source else 0,
        "conflict": int(previous.get("conflict", 0)) if same_source else 0,
        "written": int(previous.get("written", 0)) if same_source else 0,
        "failed": int(previous.get("failed", 0)) if same_source else 0,
        "backup": dict(backup),
        "last_error": "",
    }
    for index, entry in enumerate(entries[start:start + batch_size], start=start):
        result = event_store.append_event(scope, entry.event())
        if result.inserted:
            state["written"] += 1
        elif result.ok:
            marker = event_store.migration_marker(scope, entry.event_id)
            if marker == entry.block_hash:
                state["duplicate"] += 1
            else:
                state["conflict"] += 1
        else:
            state["failed"] += 1
            state["last_error"] = result.error_code or "append_failed"
            break
        state["next_offset"] = index + 1
    state["status"] = "completed" if state["next_offset"] >= len(entries) else "paused"
    state["updated_at"] = time.time()
    if not safe_write_json(_state_path(scope), state, keep_bak=True):
        raise RuntimeError("migration_state_write_failed")
    return migration_status(scope)
