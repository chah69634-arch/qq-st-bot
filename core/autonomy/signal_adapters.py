"""Pure adapters from scheduler/sensor facts to autonomy signals.

Adapters deliberately carry facts only.  They never construct assistant text,
call an LLM, mark a trigger, or send through a channel.
"""
from __future__ import annotations

import time
from datetime import datetime
from typing import Any

from core.autonomy.models import ActionMode, ProactiveSignal


# Trigger names that historically carried an assistant prompt.  They remain
# useful as observability labels, but their only runtime product is a bounded
# fact consumed by the autonomy runner.
_MIGRATED_TRIGGER_TTLS = {
    "hr_critical": 10 * 60,
    "hr_high": 10 * 60,
    "birthday_midnight": 60 * 60,
    "birthday_eve": 60 * 60,
    "birthday_afternoon": 60 * 60,
    "birthday_night": 60 * 60,
    "period_reminder": 30 * 60,
}


def registered_signal_adapter(trigger_name: str):
    """Return the producer registered for a migrated conversational trigger."""
    from core.scheduler.gating import MIGRATED_TRIGGERS
    return emit_trigger_signal if str(trigger_name or "") in MIGRATED_TRIGGERS else None


def emit_trigger_signal(
    uid: str,
    char_id: str,
    trigger_name: str,
    *,
    evidence: list[dict] | None = None,
    reason: str = "",
    priority: float = 0.2,
    urgency: float | None = None,
    confidence: float = 1.0,
    memory_query: str | dict | None = None,
    action_mode: str = ActionMode.TALK.value,
    now: float | None = None,
    dedupe_bucket_seconds: int = 15 * 60,
) -> tuple[bool, str]:
    """Queue one factual trigger candidate; never calls an LLM or channel."""
    now = time.time() if now is None else float(now)
    name = str(trigger_name or "").strip()
    if not name:
        return False, "missing_trigger"
    ttl = _MIGRATED_TRIGGER_TTLS.get(name, 20 * 60)
    signal = ProactiveSignal(
        source="sensor" if name.startswith("hr_") else "scheduler",
        reason=reason or f"A bounded {name} event is eligible for autonomy evaluation.",
        evidence=list(evidence or [{"fact": "trigger_candidate", "trigger": name}])[:12],
        created_at=now,
        expires_at=now + ttl,
        priority=priority,
        urgency=priority if urgency is None else urgency,
        confidence=confidence,
        memory_query=memory_query,
        action_mode=action_mode,
        suggested_action="message" if action_mode == ActionMode.TALK.value else "silent",
    )
    from core.autonomy import store
    key = f"trigger:{name}:{int(now // max(60, dedupe_bucket_seconds))}"
    return store.enqueue_signal(uid, char_id, signal, dedupe_key=key)


def adapt_routine(
    source: str,
    *,
    now: float | None = None,
    window: str = "",
    priority: float = 0.15,
) -> ProactiveSignal:
    now = time.time() if now is None else float(now)
    return ProactiveSignal(
        source=source,
        reason="routine",
        evidence=[{"fact": "configured_time_window", "source": source, "window": window}],
        created_at=now,
        expires_at=now + 15 * 60,
        priority=priority,
        urgency=priority,
        confidence=1.0,
        suggested_action="silent",
    )


def adapt_time_background(
    source: str,
    *,
    now: float | None = None,
    window: str = "",
) -> ProactiveSignal:
    return adapt_routine(source, now=now, window=window, priority=0.1)


def adapt_heart_rate(
    event: dict[str, Any] | None,
    *,
    now: float | None = None,
    ttl_seconds: int = 10 * 60,
) -> ProactiveSignal | None:
    if not isinstance(event, dict):
        return None
    now = time.time() if now is None else float(now)
    measured_at = float(event.get("measured_at") or event.get("received_at") or 0.0)
    if measured_at <= 0.0 or now - measured_at > ttl_seconds:
        return None
    try:
        value = float(event.get("value"))
    except (TypeError, ValueError):
        return None
    previous = event.get("previous_value", event.get("previous"))
    try:
        previous_value = float(previous) if previous is not None else None
    except (TypeError, ValueError):
        previous_value = None
    if previous_value is None:
        direction = str(event.get("direction") or "elevated")
    elif value > previous_value:
        direction = "up"
    elif value < previous_value:
        direction = "down"
    else:
        direction = "unchanged"
    confidence = event.get("confidence", 0.85)
    try:
        confidence = min(1.0, max(0.0, float(confidence)))
    except (TypeError, ValueError):
        confidence = 0.0
    urgency = _bounded_number(event.get("urgency", 0.75 if value > 120 else 0.45), default=0.0)
    try:
        measured_at_display = datetime.fromtimestamp(measured_at).astimezone().isoformat(timespec="seconds")
    except (OSError, OverflowError, ValueError):
        measured_at_display = measured_at
    return ProactiveSignal(
        source="heart_rate",
        reason="state_change",
        evidence=[{
            "fact": "heart_rate_measurement",
            "value": value,
            "previous_value": previous_value,
            "direction": direction,
            "measured_at": measured_at,
            "measured_at_local": measured_at_display,
        }],
        created_at=now,
        expires_at=min(now + ttl_seconds, measured_at + ttl_seconds),
        priority=urgency,
        urgency=urgency,
        confidence=confidence,
        suggested_action="message" if urgency >= 0.8 else "question",
    )


def adapt_memory_reactivation(
    memory: dict[str, Any] | None,
    *,
    now: float | None = None,
    ttl_seconds: int = 30 * 60,
) -> ProactiveSignal | None:
    if not isinstance(memory, dict):
        return None
    try:
        if float(memory.get("strength", 1.0) or 0.0) <= 0.5:
            return None
    except (TypeError, ValueError):
        return None
    summary = str(memory.get("narrative_summary") or memory.get("summary") or "").strip()
    if not summary:
        facts = memory.get("raw_facts")
        if isinstance(facts, list):
            summary = " ".join(str(item).strip() for item in facts if str(item).strip())[:120]
    if not summary:
        return None
    try:
        from core.scheduler.triggers.time_based import memory_key_for_recall
        memory_key = memory_key_for_recall(memory)
    except Exception:
        memory_key = str(memory.get("id") or "").strip()
    if not memory_key:
        return None
    now = time.time() if now is None else float(now)
    return ProactiveSignal(
        source="spontaneous_recall",
        reason="memory_reactivation",
        evidence=[{"fact": "eligible_memory", "memory_key": memory_key, "summary": summary[:160]}],
        memory_query=memory_key,
        created_at=now,
        expires_at=now + ttl_seconds,
        priority=_bounded_number(memory.get("strength"), default=0.35),
        urgency=_bounded_number(memory.get("urgency"), default=0.3),
        confidence=_bounded_number(memory.get("confidence", 0.8), default=0.8),
        suggested_action="suggestion",
    )


def adapt_topic_followup(
    topic: Any,
    *,
    now: float | None = None,
    ttl_seconds: int = 60 * 60,
) -> ProactiveSignal | None:
    if topic is None:
        return None
    topic_text = str(getattr(topic, "topic", "") or "").strip()
    topic_key = str(getattr(topic, "topic_key", "") or "").strip()
    if not topic_text or not topic_key:
        return None
    now = time.time() if now is None else float(now)
    mentioned_at = str(getattr(topic, "mentioned_at", "") or "")
    try:
        age_seconds = max(0.0, float(getattr(topic, "age_seconds", 0.0) or 0.0))
    except (TypeError, ValueError):
        age_seconds = 0.0
    score = _bounded_number(getattr(topic, "score", 0.5) or 0.5, default=0.5)
    return ProactiveSignal(
        source="topic_followup",
        reason="unfinished_topic",
        evidence=[{
            "fact": "unfinished_topic",
            "topic": topic_text[:120],
            "topic_key": topic_key,
            "last_mentioned_at": mentioned_at,
            "age_seconds": round(age_seconds, 1),
        }],
        memory_query=topic_key,
        created_at=now,
        expires_at=now + ttl_seconds,
        priority=score,
        urgency=score,
        confidence=score,
        suggested_action="question",
    )


def adapt_desktop_wake(
    *,
    last_seen: float | None = None,
    now: float | None = None,
    ttl_seconds: int = 10 * 60,
) -> ProactiveSignal:
    now = time.time() if now is None else float(now)
    seen = float(last_seen or now)
    offline_seconds = max(0.0, now - seen)
    return ProactiveSignal(
        source="desktop_wake",
        reason="routine",
        evidence=[{
            "fact": "desktop_session_reopened",
            "offline_seconds": round(offline_seconds, 1),
            "last_seen_at": seen,
        }],
        created_at=now,
        expires_at=now + ttl_seconds,
        priority=min(0.7, 0.2 + offline_seconds / (24 * 3600)),
        urgency=0.2,
        confidence=1.0,
        suggested_action="message",
    )


def adapt_restart(*, started_at: float, now: float | None = None) -> ProactiveSignal:
    now = time.time() if now is None else float(now)
    return ProactiveSignal(
        source="restart",
        reason="routine",
        evidence=[{"fact": "runtime_restarted", "started_at": float(started_at), "observed_at": now}],
        created_at=now,
        expires_at=now + 10 * 60,
        priority=0.05,
        urgency=0.05,
        confidence=1.0,
        suggested_action="silent",
    )


def adapt_trigger(name: str, payload: Any = None, *, now: float | None = None) -> ProactiveSignal | None:
    """Map a legacy trigger payload to a signal without executing it."""
    name = str(name or "").strip()
    if name in {"morning_greeting", "night_reminder", "midday", "random_message", "timenode"}:
        return adapt_time_background(name, now=now, window=name)
    if name in {"hr_high", "hr_critical", "heart_rate"}:
        return adapt_heart_rate(payload if isinstance(payload, dict) else None, now=now)
    if name in {"spontaneous_recall", "memory_reactivation"}:
        return adapt_memory_reactivation(payload if isinstance(payload, dict) else None, now=now)
    if name in {"topic_followup", "unfinished_topic"}:
        return adapt_topic_followup(payload, now=now)
    if name in {"desktop_wake", "reopen"}:
        return adapt_desktop_wake(last_seen=payload if isinstance(payload, (int, float)) else None, now=now)
    if name in {"restart", "runtime_restart"}:
        return adapt_restart(started_at=float(payload or now or time.time()), now=now)
    return None


def collect_external_signals(*, now: float | None = None, context: dict[str, Any] | None = None) -> list[ProactiveSignal]:
    """Collect currently available sensor/memory signals from a read-only context."""
    now = time.time() if now is None else float(now)
    context = context or {}
    result: list[ProactiveSignal] = []
    for adapter_name, payload in (
        ("heart_rate", context.get("heart_rate_event")),
        ("spontaneous_recall", context.get("memory")),
        ("topic_followup", context.get("last_mentioned")),
    ):
        signal = adapt_trigger(adapter_name, payload, now=now)
        if signal is not None:
            result.append(signal)
    if context.get("desktop_wake"):
        result.append(adapt_desktop_wake(last_seen=context.get("last_seen"), now=now))
    return result


def _bounded_number(value: Any, *, default: float = 0.0) -> float:
    try:
        return min(1.0, max(0.0, float(value)))
    except (TypeError, ValueError):
        return float(default)
