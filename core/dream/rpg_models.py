"""Content-free, durable domain model for the RPG Dream session foundation."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

RPG_SCHEMA_VERSION = 1
RPG_SESSION_ACTIVE = "active"
RPG_SESSION_CLOSED = "closed"
RPG_SESSION_UNCERTAIN = "uncertain"
RPG_SESSION_STATUSES = frozenset({RPG_SESSION_ACTIVE, RPG_SESSION_CLOSED, RPG_SESSION_UNCERTAIN})
RPG_OUTCOMES = frozenset({"critical_failure", "failure", "success_with_cost", "success", "critical_success"})
RPG_DECISIONS = frozenset({"automatic_success", "automatic_failure", "roll", "reject"})
RPG_KNOWLEDGE_STATES = frozenset({"unknown", "suspected", "known", "misbelieved"})
_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,80}$")


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RollSpec(_StrictModel):
    dice_count: int = Field(ge=1, le=10)
    dice_sides: int = Field(ge=2, le=100)
    modifier: int = Field(ge=-50, le=50)
    dc: int = Field(ge=1, le=200)


class FactProjection(_StrictModel):
    fact_id: str = Field(min_length=1, max_length=80)
    value: str = Field(min_length=1, max_length=500)
    knowledge: Literal["unknown", "suspected", "known", "misbelieved"] | None = None

    @field_validator("fact_id")
    @classmethod
    def validate_fact_id(cls, value: str) -> str:
        if not _SAFE_ID.fullmatch(value):
            raise ValueError("fact_id must be a safe identifier")
        return value


class EventProjections(_StrictModel):
    public: tuple[FactProjection, ...] = Field(default=(), max_length=32)
    player: tuple[FactProjection, ...] = Field(default=(), max_length=32)
    character: tuple[FactProjection, ...] = Field(default=(), max_length=32)
    kp_private: tuple[FactProjection, ...] = Field(default=(), max_length=32)


class SceneUpdate(_StrictModel):
    key: str = Field(min_length=1, max_length=80)
    value: str = Field(min_length=1, max_length=500)

    @field_validator("key")
    @classmethod
    def validate_key(cls, value: str) -> str:
        if not _SAFE_ID.fullmatch(value):
            raise ValueError("scene update key must be a safe identifier")
        return value


class OutcomeBranch(_StrictModel):
    projections: EventProjections
    scene_updates: tuple[SceneUpdate, ...] = Field(default=(), max_length=32)


class KpProposal(_StrictModel):
    """The only accepted kernel input. It proposes, but never states facts."""
    request_id: str = Field(min_length=1, max_length=80)
    decision: Literal["automatic_success", "automatic_failure", "roll", "reject"]
    check_type: str = Field(min_length=1, max_length=80)
    reason_code: str = Field(min_length=1, max_length=80)
    scene_id: str | None = Field(default=None, max_length=80)
    roll_spec: RollSpec | None = None
    outcome_branches: dict[str, OutcomeBranch] = Field(default_factory=dict, max_length=5)
    character_should_respond: bool = False

    @field_validator("request_id", "check_type", "reason_code", "scene_id")
    @classmethod
    def validate_safe_ids(cls, value: str | None) -> str | None:
        if value is not None and not _SAFE_ID.fullmatch(value):
            raise ValueError("proposal identifiers must be safe identifiers")
        return value

    @field_validator("outcome_branches")
    @classmethod
    def validate_branch_names(cls, value: dict[str, OutcomeBranch]) -> dict[str, OutcomeBranch]:
        if set(value) - RPG_OUTCOMES:
            raise ValueError("unknown outcome branch")
        return value

    @model_validator(mode="after")
    def validate_resolution_shape(self) -> "KpProposal":
        if self.decision == "roll":
            if self.roll_spec is None or set(self.outcome_branches) != RPG_OUTCOMES:
                raise ValueError("roll requires roll_spec and all five outcome branches")
        elif self.decision in {"automatic_success", "automatic_failure"}:
            if self.roll_spec is not None:
                raise ValueError("automatic decisions cannot contain roll_spec")
            expected = "success" if self.decision == "automatic_success" else "failure"
            if set(self.outcome_branches) != {expected}:
                raise ValueError("automatic decision requires exactly its resolved branch")
        elif self.roll_spec is not None or self.outcome_branches:
            raise ValueError("reject cannot contain roll or outcome branches")
        return self


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
