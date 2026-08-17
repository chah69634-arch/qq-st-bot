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
SCHEMA_VERSION = 2
EDGE_RELATION_TYPES = frozenset({
    "previous", "next", "same_turn", "reply_to", "triggered_by",
    "derived_from", "correction_of", "media_of",
})

_LOCKS: dict[str, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()
_PATH_GUARD = threading.RLock()
_OBSERVABILITY_LOCK = threading.Lock()
_OBSERVABILITY: dict[str, Any] = {
    "attempted": 0,
    "written": 0,
    "duplicates": 0,
    "failed": 0,
    "by_character": {},
    "by_realm": {},
}
_EDGE_OBSERVABILITY: dict[str, Any] = {
    "attempted": 0, "written": 0, "duplicates": 0, "failed": 0,
}


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
    stream: str = ""
    source: str = ""
    raw_payload_json: str = ""
    raw_text: str = ""
    visible_text: str = ""
    memory_text: str = ""
    media_refs_json: str = ""
    redaction_state: str = "unredacted"
    relation_hints_json: str = ""

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
        realm = str(self.realm or "reality")
        if realm != scope.domain:
            raise ValueError("event realm does not match scope domain")
        return EventRecord(
            event_id=event_id,
            turn_id=str(self.turn_id or ""),
            seq=int(self.seq),
            occurred_at=occurred_at,
            ingested_at=ingested_at,
            uid=scope.uid,
            char_id=scope.character_id or "",
            realm=realm,
            kind=str(self.kind or ""),
            actor=str(self.actor or ""),
            channel=str(self.channel or ""),
            stream=str(self.stream or self.channel or ""),
            source=str(self.source or ""),
            raw_payload_json=str(self.raw_payload_json or ""),
            raw_text=str(self.raw_text or ""),
            visible_text=str(self.visible_text or ""),
            memory_text=str(self.memory_text or ""),
            media_refs_json=str(self.media_refs_json or ""),
            redaction_state=str(self.redaction_state or "unredacted"),
            relation_hints_json=str(self.relation_hints_json or ""),
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
    stream TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT '',
    raw_payload_json TEXT NOT NULL DEFAULT '',
    raw_text TEXT NOT NULL DEFAULT '',
    visible_text TEXT NOT NULL DEFAULT '',
    memory_text TEXT NOT NULL DEFAULT '',
    media_refs_json TEXT NOT NULL DEFAULT '',
    redaction_state TEXT NOT NULL DEFAULT 'unredacted',
    relation_hints_json TEXT NOT NULL DEFAULT '',
    UNIQUE(uid, char_id, event_id)
);
CREATE TABLE IF NOT EXISTS event_edges (
    edge_id INTEGER PRIMARY KEY AUTOINCREMENT,
    uid TEXT NOT NULL,
    char_id TEXT NOT NULL,
    from_event_id TEXT NOT NULL,
    to_event_id TEXT NOT NULL,
    edge_type TEXT NOT NULL,
    relation_type TEXT NOT NULL DEFAULT '',
    origin TEXT NOT NULL DEFAULT 'system',
    confidence REAL NOT NULL DEFAULT 1.0,
    schema_version INTEGER NOT NULL DEFAULT 2,
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
        path = _path(scope)
        # DataPaths validates with Path.resolve(). On Windows, resolving a
        # nested non-existent path while another writer creates it can produce
        # a transient false sandbox-escape result, so prepare it under the
        # same guard as resolution.
        path.parent.mkdir(parents=True, exist_ok=True)
        return path


def _lock_for(path: Path) -> threading.RLock:
    key = str(path)
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(key, threading.RLock())


def _connect(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path, timeout=5.0, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout=5000")
    connection.execute("PRAGMA journal_mode=WAL")
    return connection


def _observe_append(result: AppendResult, scope: object) -> AppendResult:
    """Update redacted, process-local write health counters."""
    char_id = str(getattr(scope, "character_id", "") or "unknown")
    realm = str(getattr(scope, "domain", "") or "unknown")

    def update(bucket: dict[str, Any]) -> None:
        bucket["attempted"] = int(bucket.get("attempted", 0)) + 1
        if result.inserted:
            bucket["written"] = int(bucket.get("written", 0)) + 1
        elif result.ok:
            bucket["duplicates"] = int(bucket.get("duplicates", 0)) + 1
        else:
            bucket["failed"] = int(bucket.get("failed", 0)) + 1

    with _OBSERVABILITY_LOCK:
        update(_OBSERVABILITY)
        for group, key in (("by_character", char_id), ("by_realm", realm)):
            buckets = _OBSERVABILITY[group]
            update(buckets.setdefault(key, {}))
    return result


def observability_snapshot() -> dict[str, Any]:
    """Return a read-only, content-free projection of ledger write health."""
    with _OBSERVABILITY_LOCK:
        attempted = int(_OBSERVABILITY["attempted"])
        successful = int(_OBSERVABILITY["written"]) + int(_OBSERVABILITY["duplicates"])
        return {
            "scope": "process",
            "attempted": attempted,
            "written": int(_OBSERVABILITY["written"]),
            "duplicates": int(_OBSERVABILITY["duplicates"]),
            "failed": int(_OBSERVABILITY["failed"]),
            "success_rate": successful / attempted if attempted else None,
            "by_character": {key: dict(value) for key, value in _OBSERVABILITY["by_character"].items()},
            "by_realm": {key: dict(value) for key, value in _OBSERVABILITY["by_realm"].items()},
        }


def _reset_observability_for_tests() -> None:
    with _OBSERVABILITY_LOCK:
        for key in ("attempted", "written", "duplicates", "failed"):
            _OBSERVABILITY[key] = 0
        _OBSERVABILITY["by_character"] = {}
        _OBSERVABILITY["by_realm"] = {}
    with _OBSERVABILITY_LOCK:
        for key in _EDGE_OBSERVABILITY:
            _EDGE_OBSERVABILITY[key] = 0


def _initialize(connection: sqlite3.Connection) -> None:
    version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    if version > SCHEMA_VERSION:
        raise RuntimeError("unsupported_schema_version")
    connection.executescript(_SCHEMA_SQL)
    # v1 ledgers already had the compatibility edge_type column.  Additive
    # ALTERs keep those ledgers readable and preserve manually inserted edges.
    event_columns = {row[1] for row in connection.execute("PRAGMA table_info(events)")}
    if "stream" not in event_columns:
        connection.execute("ALTER TABLE events ADD COLUMN stream TEXT NOT NULL DEFAULT ''")
    if "relation_hints_json" not in event_columns:
        connection.execute("ALTER TABLE events ADD COLUMN relation_hints_json TEXT NOT NULL DEFAULT ''")
    edge_columns = {row[1] for row in connection.execute("PRAGMA table_info(event_edges)")}
    for column, definition in (
        ("relation_type", "TEXT NOT NULL DEFAULT ''"),
        ("origin", "TEXT NOT NULL DEFAULT 'system'"),
        ("confidence", "REAL NOT NULL DEFAULT 1.0"),
        ("schema_version", "INTEGER NOT NULL DEFAULT 2"),
    ):
        if column not in edge_columns:
            connection.execute(f"ALTER TABLE event_edges ADD COLUMN {column} {definition}")
    connection.execute("UPDATE event_edges SET relation_type = edge_type WHERE relation_type = ''")
    connection.execute("UPDATE event_edges SET schema_version = ? WHERE schema_version IS NULL OR schema_version = 0", (SCHEMA_VERSION,))
    if version < SCHEMA_VERSION:
        connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
    connection.commit()


def initialize(scope: MemoryScope) -> SchemaStatus:
    """Create or upgrade one scoped ledger; return status instead of raising."""
    try:
        path = _prepare_write_path(scope)
    except (TypeError, ValueError):
        return SchemaStatus(SCHEMA_NAME, SCHEMA_VERSION, None, False, False, error_code="invalid_scope")
    except Exception as exc:
        logger.warning("[event_store] initialize path preparation failed: %s", exc)
        return SchemaStatus(SCHEMA_NAME, SCHEMA_VERSION, None, False, False, error_code="database_error")
    with _lock_for(path):
        try:
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
        return _observe_append(AppendResult(False, False, event_id, "invalid_scope"), scope)
    except Exception as exc:
        logger.warning("[event_store] path preparation failed: %s", exc)
        return _observe_append(AppendResult(False, False, event_id, "database_error"), scope)
    relation_hints: dict[str, str] = {}
    try:
        if isinstance(event, Mapping):
            for relation in EDGE_RELATION_TYPES - {"previous", "next", "same_turn"}:
                value = event.get(f"{relation}_event_id")
                if value in (None, "") and isinstance(event.get(relation), str):
                    value = event.get(relation)
                if value not in (None, ""):
                    relation_hints[relation] = str(value).strip()
            # The mapping is deliberately kept out of the public projection.
            event = dict(event)
            event.setdefault("relation_hints_json", json.dumps(relation_hints, separators=(",", ":")))
        record = event if isinstance(event, EventRecord) else EventRecord.from_mapping(event)
        record = record.normalized(scope)
    except (TypeError, ValueError, KeyError):
        return _observe_append(AppendResult(False, False, event_id, "invalid_event"), scope)

    columns = tuple(EventRecord.__dataclass_fields__)
    values = tuple(getattr(record, field) for field in columns)
    placeholders = ", ".join("?" for _ in columns)
    with _lock_for(path):
        try:
            with _connect(path) as connection:
                _initialize(connection)
                connection.execute(
                    f"INSERT INTO events ({', '.join(columns)}) VALUES ({placeholders})",
                    values,
                )
                _ensure_deterministic_edges(connection, scope, record)
                connection.commit()
            return _observe_append(AppendResult(True, True, record.event_id), scope)
        except sqlite3.IntegrityError:
            # Idempotent retries are still allowed to repair deterministic
            # edges when the original transaction pre-dated edge generation.
            try:
                with _connect(path) as repair:
                    _initialize(repair)
                    existing = repair.execute(
                        "SELECT * FROM events WHERE uid = ? AND char_id = ? AND realm = ? AND event_id = ?",
                        (scope.uid, scope.character_id, scope.domain, record.event_id),
                    ).fetchone()
                    if existing is not None:
                        _ensure_deterministic_edges(repair, scope, record)
                        repair.commit()
            except Exception:
                pass
            return _observe_append(AppendResult(True, False, record.event_id, "duplicate"), scope)
        except Exception as exc:
            _edge_observe("failed")
            logger.warning("[event_store] append failed: %s", exc)
            return _observe_append(AppendResult(False, False, record.event_id, "database_error"), scope)


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


def _edge_observe(key: str) -> None:
    with _OBSERVABILITY_LOCK:
        _EDGE_OBSERVABILITY[key] = int(_EDGE_OBSERVABILITY.get(key, 0)) + 1


def _insert_edge(
    connection: sqlite3.Connection,
    scope: MemoryScope,
    from_event_id: str,
    to_event_id: str,
    relation_type: str,
    *,
    created_at: float,
) -> None:
    if relation_type not in EDGE_RELATION_TYPES or not from_event_id or not to_event_id or from_event_id == to_event_id:
        return
    # Endpoint checks are scoped and realm-bound.  This is what prevents a
    # failed/partial event write from leaving a new dangling edge.
    endpoint_count = connection.execute(
        "SELECT COUNT(*) FROM events WHERE uid = ? AND char_id = ? AND realm = ? AND event_id IN (?, ?)",
        (scope.uid, scope.character_id, scope.domain, from_event_id, to_event_id),
    ).fetchone()[0]
    if endpoint_count != 2:
        return
    _edge_observe("attempted")
    try:
        connection.execute(
            """INSERT INTO event_edges
               (uid, char_id, from_event_id, to_event_id, edge_type,
                relation_type, origin, confidence, created_at, schema_version)
               VALUES (?, ?, ?, ?, ?, ?, 'system', 1.0, ?, ?)""",
            (scope.uid, scope.character_id, from_event_id, to_event_id,
             relation_type, relation_type, created_at, SCHEMA_VERSION),
        )
        _edge_observe("written")
    except sqlite3.IntegrityError:
        _edge_observe("duplicates")
    except Exception:
        _edge_observe("failed")
        raise


def _relation_hints(row: Any) -> dict[str, str]:
    try:
        value = json.loads(str(row["relation_hints_json"] or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError, IndexError):
        return {}
    return value if isinstance(value, dict) else {}


def _ensure_deterministic_edges(
    connection: sqlite3.Connection,
    scope: MemoryScope,
    record: EventRecord,
) -> None:
    """Reconcile only the finite, deterministic edge set for this ledger.

    No model call or fuzzy matching occurs here.  Re-running this function is
    idempotent and is safe for concurrent append retries under the scope lock.
    """
    rows = connection.execute(
        """SELECT * FROM events WHERE uid = ? AND char_id = ? AND realm = ?
           ORDER BY occurred_at ASC, seq ASC, event_id ASC""",
        (scope.uid, scope.character_id, scope.domain),
    ).fetchall()
    if not rows:
        return
    now = time.time()
    # previous/next are stream-local.  ``stream`` is explicit when supplied;
    # historical rows fall back to channel, preserving old ledgers.
    streams: dict[str, list[Any]] = {}
    for row in rows:
        stream = str(row["stream"] or row["channel"] or "")
        streams.setdefault(stream, []).append(row)
    for stream_rows in streams.values():
        for previous, current in zip(stream_rows, stream_rows[1:]):
            _insert_edge(connection, scope, previous["event_id"], current["event_id"], "next", created_at=now)
            _insert_edge(connection, scope, current["event_id"], previous["event_id"], "previous", created_at=now)

    by_turn: dict[str, list[Any]] = {}
    for row in rows:
        turn_id = str(row["turn_id"] or "")
        if turn_id:
            by_turn.setdefault(turn_id, []).append(row)
    for turn_rows in by_turn.values():
        users = [row for row in turn_rows if str(row["actor"] or "") == "user"]
        for row in turn_rows:
            if str(row["actor"] or "") != "assistant":
                continue
            # A normal Reality turn has one owner event and one assistant
            # event.  Keep same_turn as a single canonical user -> assistant
            # edge; related() is bidirectional and reply_to supplies the
            # assistant -> user semantic direction without duplicating it.
            for user in users[:1]:
                _insert_edge(connection, scope, user["event_id"], row["event_id"], "same_turn", created_at=now)
                _insert_edge(connection, scope, row["event_id"], user["event_id"], "reply_to", created_at=now)

    for row in rows:
        hints = _relation_hints(row)
        for relation in ("triggered_by", "derived_from", "correction_of", "media_of", "reply_to"):
            target = str(hints.get(relation) or "")
            if target:
                _insert_edge(connection, scope, row["event_id"], target, relation, created_at=now)


def edge_observability_snapshot(scope: MemoryScope) -> dict[str, Any]:
    """Return content-free edge counts, including dangling endpoints."""
    result: dict[str, Any] = {
        "scope": {"uid": scope.uid, "char_id": scope.character_id, "realm": scope.domain},
        "edge_count": 0, "by_relation": {}, "dangling_count": 0,
        "duplicate_writes": 0, "failed_writes": 0,
    }
    path = _path(scope)
    if not path.exists():
        return result
    with _lock_for(path):
        try:
            with sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=5.0) as connection:
                version = int(connection.execute("PRAGMA user_version").fetchone()[0])
                columns = {row[1] for row in connection.execute("PRAGMA table_info(event_edges)")}
                if version != SCHEMA_VERSION or not {"relation_type", "origin", "confidence", "schema_version"} <= columns:
                    result["error_code"] = "schema_mismatch"
                    return result
                rows = connection.execute(
                    """SELECT e.relation_type, e.edge_type,
                       CASE WHEN f.event_id IS NULL OR t.event_id IS NULL THEN 1 ELSE 0 END
                       FROM event_edges e
                       LEFT JOIN events f ON f.uid=e.uid AND f.char_id=e.char_id AND f.realm=? AND f.event_id=e.from_event_id
                       LEFT JOIN events t ON t.uid=e.uid AND t.char_id=e.char_id AND t.realm=? AND t.event_id=e.to_event_id
                       WHERE e.uid=? AND e.char_id=?""",
                    (scope.domain, scope.domain, scope.uid, scope.character_id),
                ).fetchall()
            for relation, legacy_relation, dangling in rows:
                relation = str(relation or legacy_relation or "unknown")
                result["edge_count"] += 1
                result["by_relation"][relation] = result["by_relation"].get(relation, 0) + 1
                result["dangling_count"] += int(dangling)
        except Exception:
            result["error_code"] = "database_error"
    with _OBSERVABILITY_LOCK:
        result["duplicate_writes"] = int(_EDGE_OBSERVABILITY["duplicates"])
        result["failed_writes"] = int(_EDGE_OBSERVABILITY["failed"])
    return result


# Short aliases keep the adapter small while retaining one public write path.
append = append_event
get_schema_status = schema_status
