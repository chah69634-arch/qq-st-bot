"""Autonomy loop: tools are internal; only explicit talk_owner may reach turn_sink."""
from __future__ import annotations

import asyncio
import json
import time

from core.autonomy import policy, store, talk_gate
from core.autonomy.models import Disposition, Job, Run


def _system_prompt(*, talk_available: bool, character=None) -> str:
    talk_note = "talk_owner is available only for a deliberate final message." if talk_available else "用户尚未回应最近两次主动发言，本轮不可继续向用户发送消息。你仍可以进行其他允许的自主活动，也可以选择什么都不做。"
    identity = ""
    if character is not None:
        name = str(getattr(character, "name", "") or "")
        pieces = [
            str(getattr(character, "system_prompt", "") or ""),
            str(getattr(character, "personality", "") or ""),
            str(getattr(character, "scenario", "") or ""),
        ]
        identity = f" You are {name}. " + "\n".join(part for part in pieces if part)[:4000]
    return (
        "You are running an internal autonomous opportunity. This is not a chat turn. "
        "Your ordinary text is private and will never be delivered. You may call allowed tools, "
        "then either explicitly call talk_owner once or finish silently. Do not narrate tool calls. " + talk_note
    ) + identity


async def run_job(job: Job) -> Run:
    state = store.load(job.uid, job.char_id)
    run = Run(uid=job.uid, char_id=job.char_id, source=job.source, job_id=job.id)
    blocked = policy.admission(job.uid, job.char_id, state)
    if blocked:
        run.disposition = blocked; run.finished_at = time.time(); return run
    from core.conversation_gate import conversation_lock
    lock = conversation_lock(job.uid)
    if lock.locked():
        run.disposition = Disposition.BLOCKED_USER_ACTIVE.value; run.finished_at = time.time(); return run
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
    tools = policy.allowed_tools(job.char_id, state)
    mode, _ = talk_gate.check(job.uid)
    # A soft limit still exposes talk once so the model can make one explicit
    # re-decision. Hard limits remove it at schema construction time.
    talk_available = bool(state["config"].get("talk_enabled", True) and mode != "hard")
    if talk_available:
        tools.append(talk_gate.schema())
    messages = [{"role": "system", "content": _system_prompt(talk_available=talk_available, character=_character_for(job.char_id)), "_layer": "autonomy_policy"}, {"role": "user", "content": f"Autonomy opportunity source: {job.source}. Decide what to do, if anything."}]
    cfg = state["config"]
    max_steps = max(1, min(int(cfg.get("max_steps") or 4), 8))
    max_tools = max(0, min(int(cfg.get("max_tools") or 4), 8))
    max_write_tools = max(0, min(int(cfg.get("max_write_tools") or 0), max_tools))
    session = _AutonomySession()
    saw_tool = False
    pending_talk_text = ""
    confirm_available = False
    write_tool_count = 0
    deadline = time.monotonic() + max(1.0, float(cfg.get("total_timeout_seconds") or 120))
    try:
        from core import llm_client
        for _ in range(max_steps):
            if _user_became_active(job.uid):
                run.disposition = Disposition.CANCELED_BY_USER_ACTIVITY.value; break
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
                run.disposition = Disposition.COMPLETED_TOOLS_ONLY.value if saw_tool else Disposition.COMPLETED_NO_OP.value
                break
            messages.extend(turn.continuation_items or [turn.assistant_message])
            for call in turn.tool_calls:
                name, args = call["name"], call["arguments"]
                if _user_became_active(job.uid):
                    run.disposition = Disposition.CANCELED_BY_USER_ACTIVITY.value; break
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
                if len(run.tool_names) >= max_tools:
                    run.disposition = Disposition.COMPLETED_TOOLS_ONLY.value if saw_tool else Disposition.COMPLETED_NO_OP.value; return _finish(run)
                if _is_write_tool(name) and write_tool_count >= max_write_tools:
                    messages.append({"role": "tool", "tool_call_id": call["id"], "content": "write tool budget exhausted for this autonomy run"})
                    continue
                result, outcome = await _execute_tool(name, args, job, session, cfg)
                saw_tool = True; run.tool_names.append(name)
                if outcome == "outcome_unknown": run.disposition = Disposition.TOOL_OUTCOME_UNKNOWN.value; return _finish(run)
                if outcome == "failed":
                    run.disposition = Disposition.TOOL_FAILED.value
                    return _finish(run)
                if _is_write_tool(name):
                    write_tool_count += 1
                messages.append({"role": "tool", "tool_call_id": call["id"], "content": (result or "tool failed")[:1200]})
            if run.disposition == Disposition.CANCELED_BY_USER_ACTIVITY.value: break
        else:
            run.disposition = Disposition.COMPLETED_TOOLS_ONLY.value if saw_tool else Disposition.COMPLETED_NO_OP.value
    except asyncio.TimeoutError:
        run.disposition = Disposition.TIMEOUT.value
    except Exception:
        run.disposition = Disposition.LLM_FAILED.value
    return _finish(run)


def _finish(run: Run) -> Run:
    run.finished_at = time.time()
    return run


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


async def _execute_tool(name: str, args: dict, job: Job, session, cfg: dict) -> tuple[str | None, str]:
    from core.tool_dispatcher import execute
    try:
        result, ask = await asyncio.wait_for(execute(name, args, job.uid, job.uid, False, session, origin="autonomy_loop", char_id=job.char_id), timeout=float(cfg.get("tool_timeout_seconds") or 30))
    except asyncio.TimeoutError:
        return "tool timeout", "failed"
    if ask:
        return "tool requires user confirmation and was not executed", "failed"
    if result and "结果不明" in result:
        return result, "outcome_unknown"
    return result, "ok"


class _AutonomySession:
    NORMAL = "normal"
    WAITING_CONFIRM = "waiting_confirm"
    status = NORMAL
    def set_waiting_confirm(self, *_args):
        self.status = self.WAITING_CONFIRM


async def tick(uid: str, char_id: str) -> None:
    """Called only by the existing scheduler tick; creates jobs only at actual due times."""
    state = store.load(uid, char_id)
    cfg = state["config"]
    if not cfg.get("enabled"):
        return
    now = time.time()
    interval = cfg.get("interval", {})
    if interval.get("enabled") and now - store.source_last_evaluated(state, "interval") >= int(interval.get("seconds") or 0):
        store.enqueue(uid, char_id, "interval", dedupe_key=f"interval:{int(now // max(60, int(interval.get('seconds') or 60)))}")
    schedule = cfg.get("schedule", {})
    if _schedule_due(schedule, now, store.source_last_evaluated(state, "schedule")):
        store.enqueue(uid, char_id, "schedule", dedupe_key=f"schedule:{time.strftime('%Y%m%d%H%M', time.localtime(now))}")
    overflow = cfg.get("overflow", {})
    if overflow.get("enabled"):
        from core.scheduler.overflow_bucket import compute_signals
        signals = compute_signals(uid, char_id=char_id)
        if signals.bucket_score() >= float(overflow.get("threshold") or 1.6):
            key = f"overflow:{int(now // max(60, int(cfg.get('min_interval_seconds') or 900)))}"
            store.enqueue(uid, char_id, "overflow", dedupe_key=key)
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
