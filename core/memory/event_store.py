"""Scoped SQLite evidence ledger for Memory Event.

This module is deliberately independent from ``event_log`` and the prompt
pipeline.  It stores immutable evidence rows only; callers cannot issue SQL
through the public API.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping

from core.memory.path_resolver import resolve_path
from core.memory.scope import MemoryScope, require_character_id

logger = logging.getLogger(__name__)

SCHEMA_NAME = "memory_event_ledger"
SCHEMA_VERSION = 1

_LOCKS: dict[str, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()
_PATH_GUARD = threading.RLock()


@dataclass(frozen=True)
class EventRecord:
    event_id: str
    turn_id: str = ""
    seq: int = 0
    occurred_at: float = 0.0
    ingested_at: float = 0.0
    uid: str = ""
    char_id: str = ""
    realm: str = "reality"
    kind: str = ""
    actor: str = ""
    channel: str = ""
    source: str = ""
    raw_payload_json: str = ""
    raw_text: str = ""
    visible_text: str = ""
    memory_text: str = ""
    media_refs_json: str = ""
    redaction_state: str = "unredacted"

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "EventRecord":
        if not isinstance(value, Mapping):
            raise TypeError("event must be a mapping or EventRecord")
        data = dict(value)
        for field in ("raw_payload_json", "media_refs_json"):
            if field in data and not isinstance(data[field], str):
                data[field] = json.dumps(data[field], ensure_ascii=False, separators=(",", ":"))
        return cls(**{field: data[field] for field in cls.__dataclass_fields__ if field in data})

    def normalized(self, scope: MemoryScope) -> "EventRecord":
        require_character_id(scope.character_id)
        event_id = str(self.event_id).strip()
        if not event_id:
            raise ValueError("event_id must be non-empty")
        if self.uid and self.uid != scope.uid:
            raise ValueError("event uid does not match scope uid")
        if self.char_id and self.char_id != scope.character_id:
            raise ValueError("event char_id does not match scope character_id")
        now = time.time()
        occurred_at = float(self.occurred_at or now)
        ingested_at = float(self.ingested_at or now)
        return EventRecord(
            event_id=event_id,
            turn_id=str(self.turn_id or ""),
            seq=int(self.seq),
            occurred_at=occurred_at,
            ingested_at=ingested_at,
            uid=scope.uid,
            char_id=scope.character_id or "",
            realm=str(self.realm or "reality"),
            kind=str(self.kind or ""),
            actor=str(self.actor or ""),
            channel=str(self.channel or ""),
            source=str(self.source or ""),
            raw_payload_json=str(self.raw_payload_json or ""),
            raw_text=str(self.raw_text or ""),
            visible_text=str(self.visible_text or ""),
            memory_text=str(self.memory_text or ""),
            media_refs_json=str(self.media_refs_json or ""),
            redaction_state=str(self.redaction_state or "unredacted"),
        )


@dataclass(frozen=True)
class AppendResult:
    ok: bool
    inserted: bool
    event_id: str
    error_code: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SchemaStatus:
    schema_name: str
    expected_version: int
    schema_version: int | None
    exists: bool
    healthy: bool
    tables: tuple[str, ...] = ()
    error_code: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_name": self.schema_name,
            "expected_version": self.expected_version,
            "schema_version": self.schema_version,
            "exists": self.exists,
            "healthy": self.healthy,
            "tables": list(self.tables),
            "error_code": self.error_code,
        }


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS events (
    event_id TEXT PRIMARY KEY,
    turn_id TEXT NOT NULL DEFAULT '',
    seq INTEGER NOT NULL DEFAULT 0,
    occurred_at REAL NOT NULL,
    ingested_at REAL NOT NULL,
    uid TEXT NOT NULL,
    char_id TEXT NOT NULL,
    realm TEXT NOT NULL,
    kind TEXT NOT NULL,
    actor TEXT NOT NULL,
    channel TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT '',
    raw_payload_json TEXT NOT NULL DEFAULT '',
    raw_text TEXT NOT NULL DEFAULT '',
    visible_text TEXT NOT NULL DEFAULT '',
    memory_text TEXT NOT NULL DEFAULT '',
    media_refs_json TEXT NOT NULL DEFAULT '',
    redaction_state TEXT NOT NULL DEFAULT 'unredacted',
    UNIQUE(uid, char_id, event_id)
);
CREATE TABLE IF NOT EXISTS event_edges (
    edge_id INTEGER PRIMARY KEY AUTOINCREMENT,
    uid TEXT NOT NULL,
    char_id TEXT NOT NULL,
    from_event_id TEXT NOT NULL,
    to_event_id TEXT NOT NULL,
    edge_type TEXT NOT NULL,
    created_at REAL NOT NULL,
    UNIQUE(uid, char_id, from_event_id, to_event_id, edge_type)
);
CREATE TABLE IF NOT EXISTS event_topics (
    uid TEXT NOT NULL,
    char_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    topic TEXT NOT NULL,
    score REAL,
    created_at REAL NOT NULL,
    PRIMARY KEY(uid, char_id, event_id, topic)
);
CREATE INDEX IF NOT EXISTS idx_events_occurred_at ON events(occurred_at);
CREATE INDEX IF NOT EXISTS idx_events_turn_id ON events(turn_id);
CREATE INDEX IF NOT EXISTS idx_events_actor ON events(actor);
CREATE INDEX IF NOT EXISTS idx_events_source ON events(source);
CREATE INDEX IF NOT EXISTS idx_events_realm ON events(realm);
"""


def _path(scope: MemoryScope) -> Path:
    if scope.domain != "reality":
        raise ValueError("event store requires a reality scope")
    return resolve_path(scope, "event_store")


def _prepare_write_path(scope: MemoryScope) -> Path:
    """Materialize the sandbox root before concurrent resolver calls."""
    from core.sandbox import get_paths

    with _PATH_GUARD:
        get_paths().root_dir().mkdir(parents=True, exist_ok=True)
        return _path(scope)


def _lock_for(path: Path) -> threading.RLock:
    key = str(path)
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(key, threading.RLock())


def _connect(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path, timeout=5.0, check_same_thread=False)
    connection.execute("PRAGMA busy_timeout=5000")
    connection.execute("PRAGMA journal_mode=WAL")
    return connection


def _initialize(connection: sqlite3.Connection) -> None:
    version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    if version > SCHEMA_VERSION:
        raise RuntimeError("unsupported_schema_version")
    connection.executescript(_SCHEMA_SQL)
    if version < SCHEMA_VERSION:
        connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
    connection.commit()


def initialize(scope: MemoryScope) -> SchemaStatus:
    """Create or upgrade one scoped ledger; return status instead of raising."""
    try:
        path = _prepare_write_path(scope)
    except (TypeError, ValueError):
        return SchemaStatus(SCHEMA_NAME, SCHEMA_VERSION, None, False, False, error_code="invalid_scope")
    with _lock_for(path):
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with _connect(path) as connection:
                _initialize(connection)
            return schema_status(scope)
        except Exception as exc:
            logger.warning("[event_store] initialize failed: %s", exc)
            return SchemaStatus(SCHEMA_NAME, SCHEMA_VERSION, None, path.exists(), False, error_code="database_error")


def append_event(scope: MemoryScope, event: EventRecord | Mapping[str, Any]) -> AppendResult:
    """Append one immutable event, idempotently, with structured failure output."""
    if isinstance(event, EventRecord):
        event_id = event.event_id
    elif isinstance(event, Mapping):
        event_id = str(event.get("event_id", ""))
    else:
        event_id = ""
    try:
        path = _prepare_write_path(scope)
    except (AttributeError, TypeError, ValueError) as exc:
        logger.warning("[event_store] invalid scope: %s", exc)
        return AppendResult(False, False, event_id, "invalid_scope")
    try:
        record = event if isinstance(event, EventRecord) else EventRecord.from_mapping(event)
        record = record.normalized(scope)
    except (TypeError, ValueError, KeyError):
        return AppendResult(False, False, event_id, "invalid_event")

    columns = tuple(EventRecord.__dataclass_fields__)
    values = tuple(getattr(record, field) for field in columns)
    placeholders = ", ".join("?" for _ in columns)
    with _lock_for(path):
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with _connect(path) as connection:
                _initialize(connection)
                connection.execute(
                    f"INSERT INTO events ({', '.join(columns)}) VALUES ({placeholders})",
                    values,
                )
                connection.commit()
            return AppendResult(True, True, record.event_id)
        except sqlite3.IntegrityError:
            return AppendResult(True, False, record.event_id, "duplicate")
        except Exception as exc:
            logger.warning("[event_store] append failed: %s", exc)
            return AppendResult(False, False, record.event_id, "database_error")


def schema_status(scope: MemoryScope) -> SchemaStatus:
    """Read-only schema/version status; missing files are not created."""
    path = _path(scope)
    if not path.exists():
        return SchemaStatus(SCHEMA_NAME, SCHEMA_VERSION, None, False, True)
    with _lock_for(path):
        try:
            with _connect(path) as connection:
                version = int(connection.execute("PRAGMA user_version").fetchone()[0])
                tables = tuple(
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
                    ).fetchall()
                )
            healthy = version == SCHEMA_VERSION and {"events", "event_edges", "event_topics"} <= set(tables)
            return SchemaStatus(SCHEMA_NAME, SCHEMA_VERSION, version, True, healthy, tables, "" if healthy else "schema_mismatch")
        except Exception as exc:
            logger.warning("[event_store] schema status failed: %s", exc)
            return SchemaStatus(SCHEMA_NAME, SCHEMA_VERSION, None, True, False, error_code="database_error")


# Short aliases keep the adapter small while retaining one public write path.
append = append_event
get_schema_status = schema_status
