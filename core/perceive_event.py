"""
core/perceive_event.py — Unified perceive-event entry point.

P0 收口：对所有可能推进 reality turn 的入口做幂等去重 + Dream Guard 统一检查。

Design constraints:
- Process-local TTL dict (no Redis).  90-second dedup window.
- Fail-closed: dream guard check failure → BLOCKED_DREAM, not allowed through.
- char_id resolution always from active_prompt_assets.json (no hardcoded fallback).
- The gate does not call an LLM or touch short_term. Callers may explicitly
  append its metadata-only result to the existing trigger audit.

Usage:
  event = PerceiveEvent(source="desktop_wake", uid=uid, channel="desktop", kind="wake")
  result = await receive_perceive_event(event)
  if result.status != PerceiveStatus.ACCEPTED:
      return        # drop — caller must not enqueue work or fanout
  enqueue_desktop_wake_signal(...)
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)

# Entries older than this are evicted from the in-memory dedup registry.
_DEDUP_TTL_SECONDS: float = 90.0
_LOW_TRUST = "low_trust"
_HIGH_TRUST = "high_trust"
_VALID_TRUST_LEVELS = frozenset({_LOW_TRUST, _HIGH_TRUST})
# No current caller uses this source. It reserves an explicit, auditable path
# for a future direct admin stimulus without changing any gate behaviour today.
_HIGH_TRUST_SOURCES = frozenset({"admin_direct"})


def _default_trust_for_source(source: str) -> str:
    """Return the v0.1 trust label implied by an event source."""
    return _HIGH_TRUST if source in _HIGH_TRUST_SOURCES else _LOW_TRUST


class PerceiveStatus(str, Enum):
    ACCEPTED = "accepted"
    DUPLICATE = "duplicate"
    BLOCKED_DREAM = "blocked_dream"
    IGNORED = "ignored"
    ERROR = "error"


@dataclass
class PerceiveEvent:
    """
    Normalized envelope for any inbound event that may advance a reality turn.

    Fields
    ------
    source      desktop_wake / desktop_chat / qq / mobile / scheduler / sensor / tool_result
    uid         owner user id
    channel     desktop / qq / mobile / system
    kind        user_message / wake / trigger / tool_result / sensor / scheduled
    payload     arbitrary extra data (used for dedup-key hash only — no PII logged)
    event_id    caller-supplied stable id; when given, used as dedup_key directly
    char_id     active character; None → resolved from active_prompt_assets.json
    created_at  event creation epoch (defaults to time.time())
    trust       low_trust / high_trust; blank derives from source in __post_init__
    require_dream_guard
                True → dream guard must ALLOW before event is accepted
    """
    source: str
    uid: str
    channel: str
    kind: str
    payload: dict = field(default_factory=dict)
    event_id: Optional[str] = None
    char_id: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    trust: str = ""
    require_dream_guard: bool = True

    def __post_init__(self) -> None:
        if not self.trust:
            self.trust = _default_trust_for_source(self.source)
        if self.trust not in _VALID_TRUST_LEVELS:
            raise ValueError(
                f"invalid PerceiveEvent trust {self.trust!r}; "
                f"expected one of {sorted(_VALID_TRUST_LEVELS)}"
            )


@dataclass
class PerceiveResult:
    status: PerceiveStatus
    event_id: str
    dedupe_key: str
    reason: str = ""
    # event_id of the first accepted event that this is a duplicate of
    existing_turn_id: Optional[str] = None
    # The exact role scope used to construct dedupe_key. Callers that persist
    # follow-up work must reuse this value instead of resolving the active role
    # a second time after the gate.
    char_id: Optional[str] = None


# ── module-level dedup state ─────────────────────────────────────────────────
#
# _dedup_registry: dedupe_key → (first_seen_ts, first_event_id)
# Protected by _dedup_lock so concurrent coroutines see consistent state.
#
# Slot lifecycle:
#   ACCEPTED     → slot stays for _DEDUP_TTL_SECONDS (blocks duplicate in window)
#   DUPLICATE    → slot already present (detected before slot is written)
#   BLOCKED_DREAM/ERROR → slot removed so retry after dream ends is NOT blocked

_dedup_lock: asyncio.Lock = asyncio.Lock()
_dedup_registry: dict[str, tuple[float, str]] = {}


def _evict_expired(now: float) -> None:
    """Remove entries older than _DEDUP_TTL_SECONDS.  Must be called under _dedup_lock."""
    expired = [k for k, (ts, _) in _dedup_registry.items() if now - ts > _DEDUP_TTL_SECONDS]
    for k in expired:
        del _dedup_registry[k]


def _payload_hash(payload: dict) -> str:
    """Stable 12-char hex fingerprint of payload dict (no PII in logs — only hash logged)."""
    try:
        raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    except Exception:
        raw = str(payload)
    return hashlib.sha256(raw.encode()).hexdigest()[:12]


def _make_dedupe_key(event: PerceiveEvent, resolved_char: Optional[str]) -> str:
    """
    Build the dedup key for an event.

    Priority:
    1. event_id supplied by caller → "eid:<event_id>"  (exact match, cross-source)
    2. Auto key: source:uid:char:channel:kind:payload_hash:time_bucket(60s)
    """
    if event.event_id:
        return f"eid:{event.event_id}"
    bucket = int(event.created_at // 60)
    ph = _payload_hash(event.payload)
    char = resolved_char or "none"
    return f"{event.source}:{event.uid}:{char}:{event.channel}:{event.kind}:{ph}:{bucket}"


def _resolve_char_id(uid: str, char_id: Optional[str]) -> Optional[str]:
    """
    Return char_id from caller, or read active_prompt_assets.json.
    Returns None (never a default character name) if unresolvable.
    """
    if char_id:
        return char_id
    try:
        from core.sandbox import get_paths as _gp
        apa = json.loads(_gp().active_prompt_assets().read_text(encoding="utf-8"))
        cid = (apa.get("active_character") or "").strip()
        return cid or None
    except Exception:
        logger.warning("[perceive_event] char_id 无法从 active_prompt_assets 解析 uid=%s", uid)
        return None


async def receive_perceive_event(event: PerceiveEvent) -> PerceiveResult:
    """
    Single choke point for any event that could drive a reality turn.

    Steps:
    1. Resolve char_id (fail-loud: None if unresolvable, no hardcoded fallback)
    2. Generate dedupe_key
    3. TTL dedup: if already seen within _DEDUP_TTL_SECONDS → DUPLICATE
    4. Dream Guard: if blocked or unconfirmable → BLOCKED_DREAM (fail-closed)
    5. Reserve slot, return ACCEPTED

    The caller may enter its declared next stage only on ACCEPTED. Duplicate
    events must not enqueue work, fanout, or trigger post_process.
    """
    resolved_char = _resolve_char_id(event.uid, event.char_id)
    event_id = event.event_id or str(uuid.uuid4())
    dedupe_key = _make_dedupe_key(event, resolved_char)

    logger.info(
        "[perceive_event] recv source=%s uid=%s char_id=%s channel=%s kind=%s "
        "event_id=%s dedupe_key=%s trust=%s payload_len=%d",
        event.source, event.uid, resolved_char, event.channel, event.kind,
        event_id, dedupe_key, event.trust, len(json.dumps(event.payload, default=str)),
    )

    # ── 1. TTL dedup ─────────────────────────────────────────────────────────
    now = time.time()
    async with _dedup_lock:
        _evict_expired(now)
        if dedupe_key in _dedup_registry:
            first_ts, first_eid = _dedup_registry[dedupe_key]
            age = now - first_ts
            logger.warning(
                "[perceive_event] DUPLICATE dedupe_key=%s first_event_id=%s age_s=%.1f "
                "source=%s uid=%s",
                dedupe_key, first_eid, age, event.source, event.uid,
            )
            return PerceiveResult(
                status=PerceiveStatus.DUPLICATE,
                event_id=event_id,
                dedupe_key=dedupe_key,
                reason=f"duplicate of {first_eid} seen {age:.1f}s ago",
                existing_turn_id=first_eid,
                char_id=resolved_char,
            )
        # Reserve slot immediately so concurrent arrivals are rejected.
        _dedup_registry[dedupe_key] = (now, event_id)

    # ── 2. Dream Guard ───────────────────────────────────────────────────────
    # On any non-ACCEPTED outcome, evict the slot so the next attempt (e.g.
    # after the dream session ends) is not incorrectly treated as a duplicate.
    if event.require_dream_guard:
        try:
            from core.dream.dream_state import get_reality_guard_status, DreamGuardStatus
            guard = get_reality_guard_status(event.uid)
        except Exception:
            logger.error(
                "[perceive_event] dream guard check failed — fail-closed uid=%s event_id=%s",
                event.uid, event_id, exc_info=True,
            )
            async with _dedup_lock:
                _dedup_registry.pop(dedupe_key, None)
            return PerceiveResult(
                status=PerceiveStatus.BLOCKED_DREAM,
                event_id=event_id,
                dedupe_key=dedupe_key,
                reason="dream guard check raised exception (fail-closed)",
                char_id=resolved_char,
            )
        if guard != DreamGuardStatus.ALLOW:
            # BLOCK_UNCERTAIN means the dream state file is unreadable/corrupt/unknown.
            # This is fail-closed: trigger/wake/scheduler turns must NOT proceed.
            # Log at WARNING so ops can distinguish corrupt state from normal dream blocking.
            if guard == DreamGuardStatus.BLOCK_UNCERTAIN:
                logger.warning(
                    "[perceive_event] BLOCK_UNCERTAIN — dream state unreadable/corrupt, "
                    "reality turn rejected (fail-closed) "
                    "uid=%s char_id=%s source=%s kind=%s event_id=%s reason=dream_state_uncertain",
                    event.uid, resolved_char, event.source, event.kind, event_id,
                )
            else:
                logger.info(
                    "[perceive_event] BLOCKED_DREAM guard=%s uid=%s event_id=%s",
                    guard, event.uid, event_id,
                )
            async with _dedup_lock:
                _dedup_registry.pop(dedupe_key, None)
            return PerceiveResult(
                status=PerceiveStatus.BLOCKED_DREAM,
                event_id=event_id,
                dedupe_key=dedupe_key,
                reason=f"dream guard: {guard}",
                char_id=resolved_char,
            )

    logger.info(
        "[perceive_event] ACCEPTED source=%s uid=%s char_id=%s event_id=%s",
        event.source, event.uid, resolved_char, event_id,
    )
    return PerceiveResult(
        status=PerceiveStatus.ACCEPTED,
        event_id=event_id,
        dedupe_key=dedupe_key,
        reason="accepted",
        char_id=resolved_char,
    )


def record_perceive_result(event: PerceiveEvent, result: PerceiveResult) -> None:
    """Append one metadata-only gate result to the existing stimulus audit.

    Gate callers opt in explicitly so legacy trigger paths that already audit
    their assistant turn do not gain a duplicate entry. This helper never
    stores the event payload or a generated reply.
    """
    try:
        from core.memory.fixation_pipeline import _write_trigger_audit_log

        if result.status == PerceiveStatus.ACCEPTED:
            dream_guard_status = "ALLOW"
        elif result.status == PerceiveStatus.BLOCKED_DREAM:
            dream_guard_status = "BLOCKED"
        else:
            dream_guard_status = "NOT_EVALUATED"
        _write_trigger_audit_log(
            uid=event.uid,
            turn_id="",
            trigger_name=event.source,
            reply=None,
            emotion="neutral",
            char_id=str(result.char_id or event.char_id or ""),
            event_id=result.event_id,
            dedupe_key=result.dedupe_key,
            source=event.source,
            kind="stimulus",
            trust=event.trust,
            dream_guard_status=dream_guard_status,
            gate_result=result.status.value,
            did_generate_reply=False,
        )
    except Exception:
        logger.warning(
            "[perceive_event] audit write failed source=%s event_id=%s",
            event.source,
            result.event_id,
            exc_info=True,
        )


def clear_dedup_registry_for_test() -> None:
    """Test-only helper: flush the in-memory dedup registry synchronously."""
    _dedup_registry.clear()
