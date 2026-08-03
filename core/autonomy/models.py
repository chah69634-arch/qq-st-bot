from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
import time
import uuid


class TriggerSource(StrEnum):
    MANUAL = "manual"
    INTERVAL = "interval"
    SCHEDULE = "schedule"
    OVERFLOW = "overflow"


class Disposition(StrEnum):
    COMPLETED_NO_OP = "completed_no_op"
    COMPLETED_TOOLS_ONLY = "completed_tools_only"
    COMPLETED_TALK_SENT = "completed_talk_sent"
    COMPLETED_TOOLS_AND_TALK_SENT = "completed_tools_and_talk_sent"
    TALK_CANCELED = "talk_canceled"
    TALK_SOFT_BLOCKED_THEN_CANCELED = "talk_soft_blocked_then_canceled"
    TALK_SOFT_BLOCKED_THEN_SENT = "talk_soft_blocked_then_sent"
    SUPPRESSED_UNANSWERED_CAP = "suppressed_unanswered_cap"
    SUPPRESSED_DND = "suppressed_dnd"
    SUPPRESSED_PROACTIVE_OFF = "suppressed_proactive_off"
    SUPPRESSED_DAILY_BUDGET = "suppressed_daily_budget"
    BLOCKED_DREAM = "blocked_dream"
    BLOCKED_DREAM_UNCERTAIN = "blocked_dream_uncertain"
    BLOCKED_USER_ACTIVE = "blocked_user_active"
    CANCELED_BY_USER_ACTIVITY = "canceled_by_user_activity"
    EXPIRED = "expired"
    DUPLICATE = "duplicate"
    TOOL_FAILED = "tool_failed"
    TOOL_CALL_DENIED = "tool_call_denied"
    TOOL_OUTCOME_UNKNOWN = "tool_outcome_unknown"
    SELF_CAPABILITY_CHANGED = "self_capability_changed"
    SELF_CAPABILITY_REJECTED = "self_capability_rejected"
    STOPPED_SELF_DISABLED = "stopped_self_disabled"
    LLM_FAILED = "llm_failed"
    TIMEOUT = "timeout"
    LEASE_LOST = "lease_lost"
    CIRCUIT_OPEN = "circuit_open"


@dataclass
class Job:
    uid: str
    char_id: str
    source: str
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    created_at: float = field(default_factory=time.time)
    ttl_seconds: int = 20 * 60
    dedupe_key: str = ""
    status: str = "pending"
    lease_until: float = 0.0
    lease_token: str = ""
    attempts: int = 0
    next_attempt_at: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict) -> "Job":
        return cls(**{k: raw[k] for k in cls.__dataclass_fields__ if k in raw})


@dataclass
class Run:
    uid: str
    char_id: str
    source: str
    job_id: str
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    started_at: float = field(default_factory=time.time)
    finished_at: float = 0.0
    disposition: str = ""
    tool_names: list[str] = field(default_factory=list)
    events: list[dict] = field(default_factory=list)
    self_capability_changes: list[dict] = field(default_factory=list)
    talk_sent: bool = False
    talk_soft_blocked: bool = False

    def to_dict(self) -> dict:
        data = asdict(self)
        data["duration_ms"] = round(max(0.0, (self.finished_at or time.time()) - self.started_at) * 1000)
        return data
