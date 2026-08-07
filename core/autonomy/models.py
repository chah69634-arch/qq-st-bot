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


SIGNAL_VERSION = "autonomy-signal.v1"
OPPORTUNITY_VERSION = "autonomy-opportunity.v1"
SIGNAL_SCHEMA_VERSION = SIGNAL_VERSION
OPPORTUNITY_SCHEMA_VERSION = OPPORTUNITY_VERSION


class ActionMode(StrEnum):
    NONE = "none"
    REFLECT = "reflect"
    USE_TOOLS = "use_tools"
    TALK = "talk"


@dataclass(frozen=True)
class Signal:
    """A bounded system-side reason for considering one proactive opportunity."""

    source: str
    evidence: list[dict | str] = field(default_factory=list)
    reason: str = ""
    expiry: float = 0.0
    priority: float = 0.0
    memory_query: str | dict | None = None
    action_mode: str = ActionMode.NONE.value
    created_at: float = field(default_factory=time.time)
    id: str = field(default_factory=lambda: uuid.uuid4().hex)

    def __post_init__(self) -> None:
        if not str(self.source).strip():
            raise ValueError("signal source is required")
        if not isinstance(self.evidence, list):
            raise TypeError("signal evidence must be a list")
        if not isinstance(self.reason, str):
            raise TypeError("signal reason must be a string")
        if not isinstance(self.priority, (int, float)) or isinstance(self.priority, bool):
            raise TypeError("signal priority must be numeric")
        if self.action_mode not in {item.value for item in ActionMode}:
            raise ValueError(f"unknown signal action_mode: {self.action_mode!r}")

    def to_dict(self) -> dict:
        data = asdict(self)
        data["version"] = SIGNAL_VERSION
        return data

    @property
    def memory_anchor(self):
        return self.memory_query

    @property
    def action_type(self) -> str:
        return self.action_mode

    @classmethod
    def from_dict(cls, raw: dict) -> "Signal":
        if not isinstance(raw, dict):
            raise TypeError("signal must be an object")
        values = {key: raw[key] for key in cls.__dataclass_fields__ if key in raw}
        return cls(**values)


@dataclass(frozen=True)
class Opportunity:
    """The one decision unit produced by merging signals in a scheduler tick."""

    signals: list[dict] = field(default_factory=list)
    priority: float = 0.0
    reason: str = ""
    expiry: float = 0.0
    memory_query: list[str | dict] = field(default_factory=list)
    action_mode: str = ActionMode.NONE.value
    created_at: float = field(default_factory=time.time)
    id: str = field(default_factory=lambda: uuid.uuid4().hex)

    def __post_init__(self) -> None:
        if self.action_mode not in {item.value for item in ActionMode}:
            raise ValueError(f"unknown opportunity action_mode: {self.action_mode!r}")

    @property
    def version(self) -> str:
        return OPPORTUNITY_VERSION

    def to_dict(self) -> dict:
        data = asdict(self)
        data["version"] = self.version
        return data

    @property
    def memory_anchor(self):
        return self.memory_query

    @property
    def action_type(self) -> str:
        return self.action_mode

    @classmethod
    def merge(cls, signals: list[Signal], *, now: float | None = None) -> "Opportunity":
        valid = [item for item in signals if isinstance(item, Signal)]
        if not valid:
            raise ValueError("at least one signal is required")
        now = time.time() if now is None else float(now)
        # A lower expiry is the conservative boundary for the merged reason.
        expiries = [float(item.expiry) for item in valid if float(item.expiry) > 0]
        action_rank = {ActionMode.NONE.value: 0, ActionMode.REFLECT.value: 1, ActionMode.USE_TOOLS.value: 2, ActionMode.TALK.value: 3}
        action_mode = max((item.action_mode for item in valid), key=lambda value: action_rank[value])
        reasons = [item.reason.strip() for item in valid if item.reason.strip()]
        memory_query = [item.memory_query for item in valid if item.memory_query not in (None, "", [])]
        return cls(
            signals=[item.to_dict() for item in valid],
            priority=max(float(item.priority) for item in valid),
            reason="; ".join(dict.fromkeys(reasons))[:1200],
            expiry=min(expiries) if expiries else 0.0,
            memory_query=memory_query,
            action_mode=action_mode,
            created_at=now,
        )

    @classmethod
    def from_dict(cls, raw: dict) -> "Opportunity":
        if not isinstance(raw, dict):
            raise TypeError("opportunity must be an object")
        values = {key: raw[key] for key in cls.__dataclass_fields__ if key in raw}
        return cls(**values)


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


def evaluation_status_for(disposition: str) -> str:
    value = str(disposition or "")
    if value == Disposition.COMPLETED_NO_OP.value:
        return "evaluated_silent"
    if value == Disposition.COMPLETED_TOOLS_ONLY.value:
        return "tools_completed_no_talk"
    if "talk_sent" in value:
        return "talk_sent"
    if value == Disposition.CANCELED_BY_USER_ACTIVITY.value:
        return "canceled_user_activity"
    return "blocked_or_failed" if value else "unevaluated"


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
    opportunity: dict = field(default_factory=dict)
    signal_sources: list[str] = field(default_factory=list)

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
    prompt_snapshot: list[dict] = field(default_factory=list)
    talk_sent: bool = False
    talk_soft_blocked: bool = False
    opportunity_id: str = ""
    signal_count: int = 0
    evaluation_status: str = "unevaluated"

    def __post_init__(self) -> None:
        if self.evaluation_status == "unevaluated" and self.disposition:
            self.evaluation_status = evaluation_status_for(self.disposition)

    def to_dict(self) -> dict:
        data = asdict(self)
        data["duration_ms"] = round(max(0.0, (self.finished_at or time.time()) - self.started_at) * 1000)
        return data


# Explicit names for callers that prefer domain-qualified contracts.
AutonomySignal = Signal
AutonomyOpportunity = Opportunity
