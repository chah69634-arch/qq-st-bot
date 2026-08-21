"""Frozen identity contract for one reality ingress and its optional turn.

This is deliberately a data contract, not an event bus or dispatcher.  It
keeps ingress, turn, and ledger evidence identities in separate namespaces.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import time
import uuid

from core.memory.scope import MemoryScope


@dataclass(frozen=True)
class EventContext:
    schema_version: int
    scope: MemoryScope
    ingress_event_id: str
    dedupe_key: str
    source: str
    channel: str
    kind: str
    actor: str = "system"
    occurred_at: float = 0.0
    ingested_at: float = 0.0
    causation_id: str = ""
    turn_id: str = ""

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("unsupported EventContext schema_version")
        if self.scope.domain != "reality":
            raise ValueError("EventContext only permits a reality scope")
        for name in ("ingress_event_id", "dedupe_key", "source", "channel", "kind"):
            if not str(getattr(self, name) or "").strip():
                raise ValueError(f"EventContext requires {name}")
        if self.turn_id and not str(self.turn_id).strip():
            raise ValueError("turn_id must be non-empty when present")
        if self.causation_id and not str(self.causation_id).strip():
            raise ValueError("causation_id must be non-empty when present")

    @classmethod
    def from_ingress(
        cls, *, uid: str, char_id: str, ingress_event_id: str, dedupe_key: str,
        source: str, channel: str, kind: str, actor: str = "system",
        occurred_at: float | None = None, ingested_at: float | None = None,
    ) -> "EventContext":
        now = time.time()
        return cls(
            schema_version=1,
            scope=MemoryScope.reality_scope(uid, char_id),
            ingress_event_id=str(ingress_event_id), dedupe_key=str(dedupe_key),
            source=str(source), channel=str(channel), kind=str(kind), actor=str(actor),
            occurred_at=float(occurred_at if occurred_at is not None else now),
            ingested_at=float(ingested_at if ingested_at is not None else now),
            causation_id=str(ingress_event_id),
        )

    def with_turn(self, turn_id: str | None = None) -> "EventContext":
        assigned = str(turn_id or uuid.uuid4())
        return replace(self, turn_id=assigned)

    def evidence_id(self, actor: str) -> str:
        if not self.turn_id:
            raise ValueError("evidence IDs require a real turn_id")
        if actor not in {"user", "assistant"}:
            raise ValueError("evidence actor must be user or assistant")
        return f"{self.turn_id}:{actor}"

    def to_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "scope": self.scope.to_payload(),
            "ingress_event_id": self.ingress_event_id,
            "dedupe_key": self.dedupe_key,
            "turn_id": self.turn_id,
            "causation_id": self.causation_id,
            "source": self.source,
            "channel": self.channel,
            "kind": self.kind,
            "actor": self.actor,
            "occurred_at": self.occurred_at,
            "ingested_at": self.ingested_at,
        }

    @classmethod
    def from_payload(cls, payload: dict[str, object]) -> "EventContext":
        if not isinstance(payload, dict):
            raise TypeError("EventContext payload must be a dict")
        required = {
            "schema_version", "scope", "ingress_event_id", "dedupe_key",
            "turn_id", "causation_id", "source", "channel", "kind",
            "actor", "occurred_at", "ingested_at",
        }
        missing = sorted(required - set(payload))
        if missing:
            raise ValueError(f"EventContext payload missing: {', '.join(missing)}")
        return cls(
            schema_version=int(payload["schema_version"]),
            scope=MemoryScope.from_payload(payload["scope"]),
            ingress_event_id=str(payload["ingress_event_id"]),
            dedupe_key=str(payload["dedupe_key"]),
            turn_id=str(payload["turn_id"]),
            causation_id=str(payload["causation_id"]),
            source=str(payload["source"]),
            channel=str(payload["channel"]),
            kind=str(payload["kind"]),
            actor=str(payload["actor"]),
            occurred_at=float(payload["occurred_at"]),
            ingested_at=float(payload["ingested_at"]),
        )
