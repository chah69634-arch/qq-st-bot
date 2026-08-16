"""Strict models for ``presencekit-external-companion-v1``."""

from __future__ import annotations

import re
from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictStr, field_validator

CONTRACT = "presencekit-external-companion-v1"
SOURCE = "stardew-companion"
ACTIVITY_KIND = "cozy_game"
REPLY_TTL_MS = 300_000
EVENT_TTL_SECONDS = REPLY_TTL_MS / 1000
MAX_BODY_BYTES = 16 * 1024
MAX_SUMMARY_LENGTH = 512
MAX_CONTENT_LENGTH = 4000
MAX_REPLY_LENGTH = 4000
OPAQUE_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


class CompanionStatus(str, Enum):
    ACCEPTED = "accepted"
    DUPLICATE = "duplicate"
    DEFERRED = "deferred"
    MUTED = "muted"
    EXPIRED = "expired"
    REJECTED = "rejected"


class CompanionProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    origin: Literal["external_companion", "companion_phone_input"]
    authority: Literal[SOURCE]
    user_authored: StrictBool


class _CommonRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract: Literal[CONTRACT]
    kind: Literal["opportunity", "phone_message"]
    source: Literal[SOURCE]
    session_id: StrictStr
    event_id: StrictStr
    created_at: StrictStr
    activity_kind: Literal[ACTIVITY_KIND]
    salience: Literal["low", "normal", "high"]
    retention_policy: Literal["ephemeral", "bounded_observation"]
    user_authored: StrictBool
    provenance: CompanionProvenance

    @field_validator("session_id", "event_id")
    @classmethod
    def _validate_opaque_id(cls, value: str) -> str:
        if not OPAQUE_ID_RE.fullmatch(value):
            raise ValueError("opaque id must match the companion contract pattern")
        return value

    @field_validator("created_at")
    @classmethod
    def _validate_timestamp(cls, value: str) -> str:
        if not 1 <= len(value) <= 64:
            raise ValueError("created_at must be a bounded ISO-8601 timestamp")
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("created_at must be ISO-8601") from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("created_at must include a timezone")
        return value


class OpportunityRequest(_CommonRequest):
    kind: Literal["opportunity"]
    user_authored: Literal[False]
    provenance: CompanionProvenance
    summary: StrictStr = Field(min_length=1, max_length=MAX_SUMMARY_LENGTH)

    @field_validator("provenance")
    @classmethod
    def _validate_provenance(cls, value: CompanionProvenance) -> CompanionProvenance:
        if value.origin != "external_companion" or value.user_authored is not False:
            raise ValueError("opportunity provenance is invalid")
        return value


class PhoneMessageRequest(_CommonRequest):
    kind: Literal["phone_message"]
    user_authored: Literal[True]
    provenance: CompanionProvenance
    content: StrictStr = Field(min_length=1, max_length=MAX_CONTENT_LENGTH)

    @field_validator("provenance")
    @classmethod
    def _validate_provenance(cls, value: CompanionProvenance) -> CompanionProvenance:
        if value.origin != "companion_phone_input" or value.user_authored is not True:
            raise ValueError("phone_message provenance is invalid")
        return value


class ReplyProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    origin: Literal["presencekit.server"]
    authority: Literal["presencekit.server"]
    user_authored: Literal[False]


class CompanionReply(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message_id: StrictStr
    content: StrictStr = Field(min_length=1, max_length=MAX_REPLY_LENGTH)
    created_at: StrictStr
    ttl_ms: Literal[REPLY_TTL_MS]
    requires_ack: Literal[True]
    user_authored: Literal[False]
    proactive: bool | None = None
    provenance: ReplyProvenance

    @field_validator("message_id")
    @classmethod
    def _validate_message_id(cls, value: str) -> str:
        if not OPAQUE_ID_RE.fullmatch(value):
            raise ValueError("message_id must be an opaque id")
        return value

    @field_validator("created_at")
    @classmethod
    def _validate_reply_timestamp(cls, value: str) -> str:
        if not 1 <= len(value) <= 64:
            raise ValueError("reply created_at must be bounded")
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("reply created_at must be ISO-8601") from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("reply created_at must include a timezone")
        return value


class CompanionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract: Literal[CONTRACT]
    request_id: StrictStr
    status: CompanionStatus
    reply: CompanionReply | None

    @field_validator("request_id")
    @classmethod
    def _validate_request_id(cls, value: str) -> str:
        if not OPAQUE_ID_RE.fullmatch(value):
            raise ValueError("request_id must be an opaque id")
        return value


def parse_request(payload: object) -> OpportunityRequest | PhoneMessageRequest:
    """Validate one request after the router has handled contract versioning."""
    if not isinstance(payload, dict):
        raise ValueError("request body must be an object")
    kind = payload.get("kind")
    if kind == "opportunity":
        return OpportunityRequest.model_validate(payload)
    if kind == "phone_message":
        return PhoneMessageRequest.model_validate(payload)
    raise ValueError("kind must be opportunity or phone_message")


def provenance_mismatch(payload: object) -> bool:
    """Return whether a well-shaped request declares the wrong kind provenance."""
    if not isinstance(payload, dict):
        return False
    provenance = payload.get("provenance")
    if not isinstance(provenance, dict):
        return False
    kind = payload.get("kind")
    if kind == "opportunity":
        return payload.get("user_authored") is not False or (
            provenance.get("origin") != "external_companion"
            or provenance.get("authority") != SOURCE
            or provenance.get("user_authored") is not False
        )
    if kind == "phone_message":
        return payload.get("user_authored") is not True or (
            provenance.get("origin") != "companion_phone_input"
            or provenance.get("authority") != SOURCE
            or provenance.get("user_authored") is not True
        )
    return False


def error_payload(code: str, message: str, *, retryable: bool) -> dict[str, object]:
    return {"code": code, "message": message, "retryable": retryable}
