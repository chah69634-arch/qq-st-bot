"""Autonomy loop: tools are internal; only explicit talk_owner may reach turn_sink."""
from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime

from core.autonomy import policy, store, talk_gate
from core.autonomy.models import ActionMode, Disposition, Job, Run, Signal


def _system_prompt(*, talk_available: bool, character=None) -> str:
    talk_note = "talk_owner is available only for a deliberate final message." if talk_available else "用户尚未回应最近两次主动发言，本轮不可继续向用户发送消息。你仍可以进行其他允许的自主活动，也可以选择什么都不做。"
    identity = ""
    if character is not None:
        name = str(getattr(character, "name", "") or "")
        description = str(getattr(character, "description", "") or "").strip()
        identity = f" You are {name}." + (f" {description[:1200]}" if description else "")
    return (
        "You are running an internal autonomous opportunity. This is not a chat turn. "
        "Your ordinary text is private and will never be delivered. You may call allowed tools, "
        "then either explicitly call talk_owner once or finish silently. Do not narrate tool calls. " + talk_note
    ) + identity


def _context_messages(uid: str, char_id: str, *, memory_query=None) -> list[dict]:
    """Read-only, bounded memory and history for an autonomy opportunity."""
    messages: list[dict] = []
    try:
        from core.memory import short_term, user_profile, mid_term
        profile = user_profile.load(uid, char_id=char_id)
        profile_text = "; ".join(
            f"{key}: {value}" for key, value in profile.items()
            if isinstance(value, (str, int, float)) and str(value).strip()
        )[:1200]
        mid_term_text = mid_term.format_for_prompt(uid, char_id=char_id)[:1800]
        if profile_text or mid_term_text:
            messages.append({"role": "system", "content": "Read-only memory recall. Use it naturally; do not mention this source. " + (f"User profile: {profile_text}\n" if profile_text else "") + (f"Mid-term recall: {mid_term_text}" if mid_term_text else ""), "_layer": "autonomy_memory_recall"})
        for item in short_term.get_history(uid, max_turns=5, char_id=char_id):
            role, content = str(item.get("role") or ""), str(item.get("content") or "").strip()
            if item.get("_source") != "trigger_stub" and role in {"user", "assistant"} and content:
                messages.append({"role": role, "content": content[:1200], "_layer": "autonomy_recent_history"})
        query_parts = []
        query_items = [memory_query] if isinstance(memory_query, str) else (memory_query or [])
        for item in query_items:
            if isinstance(item, dict):
                query_parts.extend(str(value) for value in item.values() if isinstance(value, (str, int, float)))
            elif str(item).strip():
                query_parts.append(str(item))
        if query_parts:
            from core.memory import episodic_memory
            query = " ".join(query_parts)[:500]
            recalled = episodic_memory.retrieve(uid, query, top_k=3, char_id=char_id, allow_strengthen=False)
            if recalled:
                summaries = []
                for item in recalled[:3]:
                    if not isinstance(item, dict):
                        continue
                    summary = item.get("narrative_summary") or item.get("summary") or ""
                    if summary:
                        summaries.append(str(summary)[:500])
                if summaries:
                    messages.append({
                        "role": "system",
                        "content": "Read-only anchored memory recall (do not infer new user state): " + " | ".join(summaries),
                        "_layer": "autonomy_anchored_memory",
                    })
    except Exception:
        pass
    return messages


async def run_job(job: Job) -> Run:
    state = store.load(job.uid, job.char_id)
    opportunity = job.opportunity or {}
    run = Run(
        uid=job.uid,
        char_id=job.char_id,
        source=job.source,
        job_id=job.id,
        opportunity_id=str(opportunity.get("id") or ""),
        signal_count=len(opportunity.get("signals") or []),
        evaluation_status="evaluating",
    )
    blocked = policy.admission(job.uid, job.char_id, state)
    if blocked:
        run.disposition = blocked; return _finish(run)
    from core.conversation_gate import conversation_lock
    lock = conversation_lock(job.uid)
    if lock.locked():
        run.disposition = Disposition.BLOCKED_USER_ACTIVE.value; return _finish(run)
    lease_lost = asyncio.Event()

    async def _keep_lease() -> None:
        while True:
            await asyncio.sleep(20)
            if not store.renew(job):
                lease_lost.set()
                return

    keeper = asyncio.create_task(_keep_lease())
    try:
        async with lock:
            result = await _run_locked(job, state, run)
        if lease_lost.is_set():
            result.disposition = Disposition.LEASE_LOST.value
        return result
    finally:
        keeper.cancel()


async def _run_locked(job: Job, state: dict, run: Run) -> Run:
    tools, self_context = _runtime_tools(job.uid, job.char_id, state)
    mode, _ = talk_gate.check(job.uid)
    # A soft limit still exposes talk once so the model can make one explicit
    # re-decision. Hard limits remove it at schema construction time.
    talk_available = bool(state["config"].get("talk_enabled", True) and mode != "hard")
    if talk_available:
        tools.append(talk_gate.schema())
    messages = [{"role": "system", "content": _system_prompt(talk_available=talk_available, character=_character_for(job.char_id)), "_layer": "autonomy_policy"}]
    messages.extend(_context_messages(job.uid, job.char_id, memory_query=(job.opportunity or {}).get("memory_query")))
    if self_context is not None:
        messages.append(_self_context_message(self_context))
    messages.append({"role": "system", "content": _opportunity_context(job), "_layer": "autonomy_opportunity"})
    messages.append({"role": "user", "content": "Evaluate this opportunity and decide what to do, if anything."})
    run.prompt_snapshot = [{key: value for key, value in message.items() if key in {"role", "content", "_layer"}} for message in messages]
    cfg = state["config"]
    max_steps = max(1, min(int(cfg.get("max_steps") or 4), 8))
    max_tools = max(0, min(int(cfg.get("max_tools") or 4), 8))
    max_write_tools = max(0, min(int(cfg.get("max_write_tools") or 0), max_tools))
    session = _AutonomySession()
    saw_tool = False
    saw_self_change = False
    pending_talk_text = ""
    confirm_available = False
    write_tool_count = 0
    deadline = time.monotonic() + max(1.0, float(cfg.get("total_timeout_seconds") or 120))
    try:
        from core import llm_client
        for _ in range(max_steps):
            if _user_became_active(job.uid):
                run.disposition = Disposition.CANCELED_BY_USER_ACTIVITY.value; break
            tools, self_context = _runtime_tools(job.uid, job.char_id, state)
            if talk_available:
                tools.append(talk_gate.schema())
            active_tools = list(tools)
            if confirm_available:
                # A soft timing block is one explicit re-decision, not another
                # chance to continue autonomous tool work before speaking.
                active_tools = [talk_gate.confirm_schema()]
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise asyncio.TimeoutError
            turn = await asyncio.wait_for(
                llm_client.chat_turn(messages, active_tools, char_id=job.char_id, is_proactive=True),
                timeout=remaining,
            )
            if not turn.tool_calls:
                run.disposition = _completed_disposition(saw_tool, saw_self_change)
                break
            messages.extend(turn.continuation_items or [turn.assistant_message])
            for call in turn.tool_calls:
                name, args = call["name"], call["arguments"]
                if _user_became_active(job.uid):
                    run.disposition = Disposition.CANCELED_BY_USER_ACTIVITY.value; break
                allowed_names = {((item.get("function") or item).get("name")) for item in active_tools}
                if name not in allowed_names:
                    _record_event(run, "tool_call_denied", tool_name=name, reason="not_in_current_effective_allowlist")
                    run.disposition = Disposition.TOOL_CALL_DENIED.value
                    return _finish(run)
                if name == "talk_owner":
                    gate_mode, gate_reason = talk_gate.check(job.uid, allow_soft=True)
                    if gate_mode == "soft" and not confirm_available:
                        pending_talk_text = str(args.get("text") or "")
                        confirm_available = True; run.talk_soft_blocked = True
                        messages.append({"role": "tool", "tool_call_id": call["id"], "content": json.dumps({"status": "soft_blocked", "reason": gate_reason}, ensure_ascii=False)})
                        continue
                    ok, reason = await talk_gate.send(job.uid, job.char_id, str(args.get("text") or ""), source=job.source, run_id=run.id)
                    run.talk_sent = ok
                    if ok:
                        run.disposition = Disposition.COMPLETED_TOOLS_AND_TALK_SENT.value if saw_tool else Disposition.COMPLETED_TALK_SENT.value
                    else:
                        run.disposition = reason if reason in Disposition._value2member_map_ else Disposition.TALK_CANCELED.value
                    return _finish(run)
                if name == "confirm_talk" and confirm_available:
                    action = str(args.get("action") or "cancel")
                    if action != "send_anyway":
                        run.disposition = Disposition.TALK_SOFT_BLOCKED_THEN_CANCELED.value
                        return _finish(run)
                    text = str(args.get("revised_text") or pending_talk_text)
                    ok, reason = await talk_gate.send(job.uid, job.char_id, text, source=job.source, run_id=run.id, bypass_soft_once=True)
                    run.talk_sent = ok
                    run.disposition = Disposition.TALK_SOFT_BLOCKED_THEN_SENT.value if ok else (reason if reason in Disposition._value2member_map_ else Disposition.TALK_SOFT_BLOCKED_THEN_CANCELED.value)
                    return _finish(run)
                if len([tool for tool in run.tool_names if tool != "manage_self_capability"]) >= max_tools:
                    run.disposition = _completed_disposition(saw_tool, saw_self_change); return _finish(run)
                if name != "manage_self_capability" and _is_write_tool(name) and write_tool_count >= max_write_tools:
                    messages.append({"role": "tool", "tool_call_id": call["id"], "content": "write tool budget exhausted for this autonomy run"})
                    continue
                result, outcome = await _execute_tool(name, args, job, session, cfg, run)
                run.tool_names.append(name)
                if outcome == "outcome_unknown": run.disposition = Disposition.TOOL_OUTCOME_UNKNOWN.value; return _finish(run)
                if outcome == "denied":
                    run.disposition = Disposition.TOOL_CALL_DENIED.value
                    return _finish(run)
                if outcome == "failed":
                    run.disposition = Disposition.TOOL_FAILED.value
                    return _finish(run)
                if name == "manage_self_capability":
                    record = _self_change_audit(job.uid, job.char_id, str(args.get("action_id") or ""))
                    if record is None or record.get("result") not in {"applied", "idempotent"}:
                        _record_event(run, "self_capability_rejected", tool_name=name, action_id=str(args.get("action_id") or ""), reason=str((record or {}).get("result") or "audit_missing"))
                        run.disposition = Disposition.SELF_CAPABILITY_REJECTED.value
                        return _finish(run)
                    change = {"action_id": record.get("action_id"), "capability_id": record.get("capability_id"), "revision_before": record.get("revision_before"), "revision_after": record.get("revision_after"), "old_agent_value": record.get("old_value"), "new_agent_value": record.get("new_value"), "old_effective_value": record.get("old_effective_value"), "new_effective_value": record.get("new_effective_value")}
                    run.self_capability_changes.append(change)
                    _record_event(run, "self_capability_changed", **change)
                    saw_self_change = True
                    tools, self_context = _runtime_tools(job.uid, job.char_id, state)
                    if self_context is not None:
                        messages.append(_self_context_message(self_context))
                    if not _autonomy_still_enabled(job.uid, job.char_id, state):
                        run.disposition = Disposition.STOPPED_SELF_DISABLED.value
                        return _finish(run)
                else:
                    saw_tool = True
                if name != "manage_self_capability" and _is_write_tool(name):
                    write_tool_count += 1
                messages.append({"role": "tool", "tool_call_id": call["id"], "content": (result or "tool failed")[:1200]})
            if run.disposition == Disposition.CANCELED_BY_USER_ACTIVITY.value: break
        else:
            run.disposition = _completed_disposition(saw_tool, saw_self_change)
    except asyncio.TimeoutError:
        run.disposition = Disposition.TIMEOUT.value
    except Exception:
        run.disposition = Disposition.LLM_FAILED.value
    return _finish(run)


def _finish(run: Run) -> Run:
    run.finished_at = time.time()
    disposition = str(run.disposition or "")
    if disposition == Disposition.COMPLETED_NO_OP.value:
        run.evaluation_status = "evaluated_silent"
    elif disposition == Disposition.COMPLETED_TOOLS_ONLY.value:
        run.evaluation_status = "tools_completed_no_talk"
    elif "talk_sent" in disposition:
        run.evaluation_status = "talk_sent"
    elif disposition == Disposition.CANCELED_BY_USER_ACTIVITY.value:
        run.evaluation_status = "canceled_user_activity"
    elif disposition:
        run.evaluation_status = "blocked_or_failed"
    return run


def _opportunity_context(job: Job) -> str:
    """Render only the versioned signal facts; the model never receives a bare trigger source."""
    opportunity = job.opportunity or {}
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    facts = []
    for signal in opportunity.get("signals") or []:
        if not isinstance(signal, dict):
            continue
        evidence = signal.get("evidence") or []
        facts.append({
            "source": signal.get("source", ""),
            "evidence": evidence[:8] if isinstance(evidence, list) else str(evidence)[:800],
            "reason": str(signal.get("reason") or "")[:500],
            "priority": signal.get("priority", 0),
            "expiry": signal.get("expiry", 0),
            "action_mode": signal.get("action_mode", ActionMode.NONE.value),
        })
    payload = {
        "version": opportunity.get("version", "autonomy-opportunity.v1"),
        "opportunity_id": opportunity.get("id", ""),
        "priority": opportunity.get("priority", 0),
        "reason": str(opportunity.get("reason") or "")[:1200],
        "expiry": opportunity.get("expiry", 0),
        "memory_query": opportunity.get("memory_query") or [],
        "action_mode": opportunity.get("action_mode", ActionMode.NONE.value),
        "signals": facts,
        "reality_time": now,
        "reality_time_policy": "Use this timestamp as the only current-time fact; do not infer user state from greetings or time-of-day labels.",
    }
    return "Autonomy opportunity facts (system-provided, not user claims): " + json.dumps(payload, ensure_ascii=False)


def _record_event(run: Run, status: str, **details) -> None:
    run.events.append({"status": status, **{key: value for key, value in details.items() if value not in (None, "")}})


def _completed_disposition(saw_tool: bool, saw_self_change: bool) -> str:
    if saw_tool:
        return Disposition.COMPLETED_TOOLS_ONLY.value
    if saw_self_change:
        return Disposition.SELF_CAPABILITY_CHANGED.value
    return Disposition.COMPLETED_NO_OP.value


def _self_context_message(context: dict) -> dict:
    return {
        "role": "system",
        "content": f"Self Capability control state: {json.dumps(context, ensure_ascii=False)}. You may use manage_self_capability only for these IDs, with this revision and a new action_id.",
        "_layer": "autonomy_self_management",
    }


def _runtime_tools(uid: str, char_id: str, state: dict) -> tuple[list[dict], dict | None]:
    """Build a fresh autonomy tool surface; never reuse a stale capability grant."""
    tools = policy.allowed_tools(uid, char_id, state)
    from core.self_management.service import agent_gateway_context
    from core.tool_dispatcher import _TOOL_REGISTRY, _is_tool_enabled
    context = agent_gateway_context(uid, char_id)
    gateway = _TOOL_REGISTRY.get("manage_self_capability")
    if context is not None and isinstance(gateway, dict) and _is_tool_enabled("manage_self_capability"):
        tools.append({"type": "function", "function": {"name": "manage_self_capability", "description": gateway["description"], "parameters": gateway["parameters"]}})
    else:
        context = None
    return tools, context


def _self_change_audit(uid: str, char_id: str, action_id: str) -> dict | None:
    from core.self_management import store as self_store
    return next((row for row in reversed(self_store.read_audit(uid, char_id, limit=200)) if row.get("action_id") == action_id and row.get("source") == "autonomy_self_management"), None)


def _autonomy_still_enabled(uid: str, char_id: str, state: dict) -> bool:
    from core.self_management.policy import autonomy_enabled
    return autonomy_enabled(uid, char_id, bool(state["config"].get("enabled")))


def _user_became_active(uid: str) -> bool:
    from core.scheduler.loop import _user_active_recently
    return bool(_user_active_recently())


def _is_write_tool(name: str) -> bool:
    from core.tool_dispatcher import _TOOL_REGISTRY, get_tool_effect, is_side_effect_tool
    info = _TOOL_REGISTRY.get(name, {})
    return (get_tool_effect(name) or ("write" if is_side_effect_tool(name) else "read")) != "read"


def _character_for(char_id: str):
    """Read the intended character without creating a new Pipeline or prompt audit."""
    try:
        from core import pipeline_registry
        pipeline = pipeline_registry.get()
        if pipeline is not None and getattr(pipeline, "_active_character_id", None) == char_id:
            return pipeline.character
        from core.character_loader import load
        return load(char_id)
    except Exception:
        return None


async def _execute_tool(name: str, args: dict, job: Job, session, cfg: dict, run: Run) -> tuple[str | None, str]:
    from core.mcp_client import audit_context
    from core.self_management.service import autonomy_audit_context
    from core.tool_dispatcher import execute
    statuses: list[str] = []

    async def observe(kind: str, **_kwargs) -> None:
        statuses.append(kind)

    origin = "autonomy_self_management" if name == "manage_self_capability" else "autonomy_loop"
    try:
        with audit_context(f"autonomy:{run.id}:{job.id}"), autonomy_audit_context(run_id=run.id, job_id=job.id):
            result, ask = await asyncio.wait_for(execute(name, args, job.uid, job.uid, False, session, origin=origin, char_id=job.char_id, tool_status_observer=observe), timeout=float(cfg.get("tool_timeout_seconds") or 30))
    except asyncio.TimeoutError:
        return "tool timeout", "failed"
    if ask:
        return "tool requires user confirmation and was not executed", "denied"
    if "outcome_unknown" in statuses:
        return result, "outcome_unknown"
    if "failed" in statuses:
        return result, "failed"
    if "finished" not in statuses:
        return result, "denied"
    _record_event(run, "tool_executed", tool_name=name, origin=origin, mcp_audit_id=(f"autonomy:{run.id}:{job.id}" if name.startswith("mcp__") else ""))
    return result, "ok"


class _AutonomySession:
    NORMAL = "normal"
    WAITING_CONFIRM = "waiting_confirm"
    status = NORMAL
    def set_waiting_confirm(self, *_args):
        self.status = self.WAITING_CONFIRM


async def tick(uid: str, char_id: str) -> None:
    """Collect all due signals, merge one opportunity, then consume at most one job."""
    state = store.load(uid, char_id)
    cfg = state["config"]
    if not cfg.get("enabled"):
        return
    from core.self_management.policy import autonomy_enabled, autonomy_min_interval
    if not autonomy_enabled(uid, char_id, bool(cfg.get("enabled"))):
        return
    effective_minimum = autonomy_min_interval(uid, char_id, int(cfg.get("min_interval_seconds") or 0))
    now = time.time()
    due_signals: list[Signal] = []
    dedupe_parts: list[str] = []
    interval = cfg.get("interval", {})
    if interval.get("enabled") and now - store.source_last_evaluated(state, "interval") >= int(interval.get("seconds") or 0):
        seconds = max(60, int(interval.get("seconds") or 60))
        due_signals.append(Signal(
            source="interval",
            evidence=[{"fact": "configured_interval_elapsed", "elapsed_seconds": max(0, int(now - store.source_last_evaluated(state, "interval"))), "threshold_seconds": seconds}],
            reason="A configured autonomy evaluation interval elapsed.",
            expiry=now + min(seconds, 20 * 60),
            priority=0.2,
            memory_query=None,
            action_mode=ActionMode.REFLECT.value,
        ))
        dedupe_parts.append(f"interval:{int(now // seconds)}")
    schedule = cfg.get("schedule", {})
    if _schedule_due(schedule, now, store.source_last_evaluated(state, "schedule")):
        due_signals.append(Signal(
            source="schedule",
            evidence=[{"fact": "configured_schedule_due", "configured_time": str(schedule.get("time") or ""), "observed_at": datetime.fromtimestamp(now).astimezone().isoformat(timespec="seconds")}],
            reason="A configured autonomy evaluation time is due.",
            expiry=now + 10 * 60,
            priority=0.4,
            memory_query=None,
            action_mode=ActionMode.REFLECT.value,
        ))
        dedupe_parts.append(f"schedule:{time.strftime('%Y%m%d%H%M', time.localtime(now))}")
    overflow = cfg.get("overflow", {})
    if overflow.get("enabled"):
        from core.scheduler.overflow_bucket import compute_signals
        signals = compute_signals(uid, char_id=char_id)
        score = signals.bucket_score()
        threshold = float(overflow.get("threshold") or 1.6)
        if score >= threshold:
            due_signals.append(Signal(
                source="overflow",
                evidence=[{
                    "fact": "overflow_threshold_reached",
                    "score": round(score, 4),
                    "threshold": threshold,
                    "components": {
                        "time_gap": signals.time_gap_score,
                        "episodic": signals.episodic_score,
                        "hidden_need": signals.hidden_need_score,
                        "garden": signals.garden_score,
                        "mood": signals.mood_score,
                    },
                    "top_signal": signals.top_signal,
                }],
                reason="Several bounded autonomy reasons accumulated above the configured threshold.",
                expiry=now + max(5 * 60, min(effective_minimum or 15 * 60, 20 * 60)),
                priority=min(1.0, score / max(threshold, 0.01)),
                memory_query=({"topic": signals.top_signal_detail} if signals.top_signal == "episodic" and signals.top_signal_detail else None),
                action_mode=ActionMode.REFLECT.value,
            ))
            dedupe_parts.append(f"overflow:{int(now // max(60, effective_minimum or 900))}")
    if due_signals:
        expiry = min((signal.expiry for signal in due_signals if signal.expiry > now), default=now + 20 * 60)
        store.enqueue_opportunity(
            uid,
            char_id,
            due_signals,
            dedupe_key="|".join(sorted(dedupe_parts)),
            ttl_seconds=max(60, min(int(expiry - now), 3600)),
        )
    job = store.claim_due(uid, char_id)
    if job is None: return
    run = await run_job(job)
    store.finish(job, run, retry=run.disposition in {Disposition.BLOCKED_DREAM.value, Disposition.BLOCKED_DREAM_UNCERTAIN.value})


def _schedule_due(cfg: dict, now: float, last: float) -> bool:
    if not cfg.get("enabled"): return False
    try: hour, minute = (int(x) for x in str(cfg.get("time") or "").split(":"))
    except Exception: return False
    try:
        from datetime import datetime
        from zoneinfo import ZoneInfo
        zone_name = str(cfg.get("timezone") or "local")
        local = datetime.fromtimestamp(now, None if zone_name == "local" else ZoneInfo(zone_name))
    except Exception:
        return False
    if local.weekday() not in set(cfg.get("weekdays") or []): return False
    if not _inside_schedule_window(local.hour, local.minute, cfg.get("window") or []): return False
    due = local.hour == hour and local.minute == minute
    # Default restart policy is skip: exact-minute scheduling deliberately does
    # not replay all missed slots. One bounded catch-up is possible only when
    # explicitly requested and a slot was missed in the immediately preceding
    # window.
    if not due and cfg.get("restart_miss_policy") == "catch_up_once":
        scheduled = local.replace(hour=hour, minute=minute, second=0, microsecond=0).timestamp()
        due = 0 < now - scheduled <= 60 * 60 and last < scheduled
    return due and now - last > 55


def _inside_schedule_window(hour: int, minute: int, window: list | tuple) -> bool:
    if not window:
        return True
    if not isinstance(window, (list, tuple)) or len(window) != 2:
        return False
    try:
        def value(raw):
            h, m = (int(x) for x in str(raw).split(":")); return h * 60 + m
        start, end, current = value(window[0]), value(window[1]), hour * 60 + minute
    except Exception:
        return False
    return start <= current <= end if start <= end else current >= start or current <= end
