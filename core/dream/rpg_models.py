"""Content-free, durable domain model for the RPG Dream session foundation."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

RPG_SCHEMA_VERSION = 1
RPG_SESSION_ACTIVE = "active"
RPG_SESSION_CLOSED = "closed"
RPG_SESSION_UNCERTAIN = "uncertain"
RPG_SESSION_STATUSES = frozenset({RPG_SESSION_ACTIVE, RPG_SESSION_CLOSED, RPG_SESSION_UNCERTAIN})


@dataclass(frozen=True)
class RpgCore:
    """Frozen identity and cursors. Prompt and gameplay text never live here."""
    dream_id: str
    script_id: str
    owner_uid: str
    char_id: str
    created_at: float
    updated_at: float
    schema_version: int = RPG_SCHEMA_VERSION
    status: str = RPG_SESSION_ACTIVE
    active_branch_id: str | None = None
    active_round_id: str | None = None
    round_status: str = "idle"
    next_round_seq: int = 1
    next_event_seq: int = 1
    scene_revision: int = 0
    last_error_code: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "RpgCore":
        if not isinstance(raw, dict):
            raise ValueError("rpg session must be a mapping")
        for key in ("dream_id", "script_id", "owner_uid", "char_id"):
            if not isinstance(raw.get(key), str) or not raw[key].strip():
                raise ValueError(f"rpg session missing {key}")
        if int(raw.get("schema_version", 0)) != RPG_SCHEMA_VERSION:
            raise ValueError("unsupported rpg session schema")
        if raw.get("status") not in RPG_SESSION_STATUSES:
            raise ValueError("invalid rpg session status")
        try:
            created_at, updated_at = float(raw["created_at"]), float(raw["updated_at"])
            next_round_seq, next_event_seq = int(raw.get("next_round_seq", 1)), int(raw.get("next_event_seq", 1))
            scene_revision = int(raw.get("scene_revision", 0))
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("invalid rpg session counters") from exc
        if next_round_seq < 1 or next_event_seq < 1 or scene_revision < 0:
            raise ValueError("invalid rpg session counter range")
        if not isinstance(raw.get("round_status", "idle"), str) or not raw.get("round_status", "idle"):
            raise ValueError("invalid rpg round status")
        return cls(dream_id=raw["dream_id"], script_id=raw["script_id"], owner_uid=raw["owner_uid"],
                   char_id=raw["char_id"], created_at=created_at, updated_at=updated_at,
                   status=raw["status"], active_branch_id=raw.get("active_branch_id"),
                   active_round_id=raw.get("active_round_id"), round_status=raw.get("round_status", "idle"),
                   next_round_seq=next_round_seq, next_event_seq=next_event_seq, scene_revision=scene_revision,
                   last_error_code=raw.get("last_error_code"))
