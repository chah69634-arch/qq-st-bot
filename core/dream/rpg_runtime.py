"""Playable RPG Dream turn orchestration, isolated from the Reality pipeline."""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
import uuid
from typing import Any

from core.conversation_gate import conversation_lock
from core.dream import rpg_store
from core.dream.rpg_character_marker import parse_character_marker
from core.dream.rpg_engine import RpgKernelError, apply_proposal
from core.dream.rpg_models import KpProposal, RpgEntry, RpgTurnResponse
from core.dream.rpg_projection import derive_snapshot, events_for_branch

_INFLIGHT: set[tuple[str, str]] = set()
_MAX_EVENT_TAIL = 12
_KP_TIMEOUT = 30.0
_CHARACTER_TIMEOUT = 45.0


def _digest(*, lane: str, message: str, expected_revision: int) -> str:
    raw = json.dumps({"lane": lane, "message": message, "expected_revision": expected_revision}, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def _entry(*, lane: str, kind: str, content: str, correlation_id: str, revision: int, branch_id: str) -> dict[str, Any]:
    return {
        "entry_id": "entry_" + uuid.uuid4().hex,
        "lane": lane,
        "kind": kind,
        "content": content[:12000],
        "ts": time.time(),
        "correlation_id": correlation_id,
        "revision": revision,
        "branch_id": branch_id,
    }


def _extract_json(raw: str) -> dict[str, Any]:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text
        if text.endswith("```"):
            text = text[:-3]
    value = json.loads(text.strip())
    if not isinstance(value, dict):
        raise ValueError("proposal must be an object")
    return value


def _kp_prompt(script: dict[str, Any], snapshot: dict[str, Any], *, lane: str, message: str, events: list[dict[str, Any]], request_id: str) -> list[dict[str, str]]:
    safe_script = {key: value for key, value in script.items() if key in {"id", "title", "stages", "private_truths"}}
    body = {
        "contract": "KpProposal JSON only; no prose and no character dialogue",
        "request_id": request_id,
        "lane": lane,
        "player_input": message,
        "script": safe_script,
        "current_snapshot": snapshot,
        "recent_events": events[-_MAX_EVENT_TAIL:],
        "rules": ["Do not choose or request a seed", "For roll submit all five outcome_branches", "Never write character dialogue"],
    }
    return [
        {"role": "system", "content": "You are a neutral RPG adjudicator. Return one strict KpProposal JSON object."},
        {"role": "user", "content": json.dumps(body, ensure_ascii=False, separators=(",", ":"))},
    ]


def _character_prompt(character: Any, snapshot: dict[str, Any], *, message: str, entries: list[dict[str, Any]], check_intent: str | None = None) -> list[dict[str, str]]:
    card = {
        "name": str(getattr(character, "name", "AI")),
        "description": str(getattr(character, "description", ""))[:4000],
        "personality": str(getattr(character, "personality", ""))[:4000],
        "scenario": str(getattr(character, "scenario", ""))[:2000],
    }
    visible_entries = [
        {"lane": row.get("lane"), "kind": row.get("kind"), "content": row.get("content", "")[:3000]}
        for row in entries[-_MAX_EVENT_TAIL:]
        if row.get("lane") in {"character", "shared"}
    ]
    directive = "Respond naturally as the active character. Do not speak as the KP or invent hidden facts."
    if check_intent:
        directive += " If the requested check is resolved, you may emit exactly one <C>intent</C> marker for a follow-up action."
    payload = {"directive": directive, "character_card": card, "rpg_view": {"scene": snapshot.get("scene", {}), "shared_facts": snapshot.get("shared_facts", {}), "character_knowledge": snapshot.get("character_knowledge", {})}, "recent_transcript": visible_entries, "user_action": message, "check_intent": check_intent}
    return [
        {"role": "system", "content": "You are the active RPG character. " + directive},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False, separators=(",", ":"))},
    ]


async def _call(messages: list[dict[str, str]], *, category: str, char_id: str, timeout: float) -> str:
    from core import llm_client
    return await asyncio.wait_for(llm_client.chat(messages, call_category=category, char_id=char_id, max_tokens_override=900), timeout=timeout)


def _load_context(uid: str, dream_id: str, char_id: str):
    core, health = rpg_store.load(uid, dream_id, char_id=char_id)
    if core is None or health != "ok":
        raise RpgKernelError("RPG_SESSION_UNCERTAIN" if health == "invalid" else "RPG_NOT_ACTIVE")
    if core.status != "active":
        raise RpgKernelError("RPG_NOT_ACTIVE")
    events, events_health = rpg_store.read_events_with_health(uid, dream_id, char_id=char_id)
    if events_health == "invalid":
        raise RpgKernelError("RPG_SESSION_UNCERTAIN")
    snapshot = derive_snapshot(events, active_branch_id=core.active_branch_id, revision=core.scene_revision)
    return core, events, snapshot


async def run_turn(uid: str, *, dream_id: str, request_id: str, lane: str, message: str, expected_revision: int, char_id: str) -> RpgTurnResponse:
    if lane not in {"character", "kp"}:
        raise RpgKernelError("RPG_INVALID_LANE")
    if not isinstance(message, str) or not message.strip() or len(message.strip()) > 12000:
        raise RpgKernelError("RPG_INVALID_MESSAGE")
    message = message.strip()
    digest = _digest(lane=lane, message=message, expected_revision=expected_revision)
    async with conversation_lock(uid):
        core, events, snapshot = _load_context(uid, dream_id, char_id)
        receipts = rpg_store.load_turn_receipts(uid, dream_id, char_id=char_id)
        previous = receipts.get(request_id)
        if previous:
            if previous.get("digest") != digest:
                raise RpgKernelError("RPG_IDEMPOTENCY_CONFLICT")
            return RpgTurnResponse.model_validate(previous["response"])
        key = (uid, dream_id)
        if key in _INFLIGHT:
            raise RpgKernelError("RPG_ROUND_BUSY")
        if core.scene_revision != expected_revision:
            raise RpgKernelError("RPG_REVISION_CONFLICT")
        _INFLIGHT.add(key)
        try:
            round_id = f"round_{core.next_round_seq}"
            branch_id = core.active_branch_id or "root"
            entries: list[dict[str, Any]] = []
            user_entry = _entry(lane=lane, kind="user_action", content=message, correlation_id=request_id, revision=core.scene_revision, branch_id=branch_id)
            if not rpg_store.append_transcript(uid, dream_id, user_entry, char_id=char_id):
                raise RpgKernelError("RPG_TRANSCRIPT_WRITE_FAILED")
            from core.dream.scenario_loader import load_script
            try:
                script = load_script(core.script_id)
            except Exception as exc:
                raise RpgKernelError("RPG_SCRIPT_UNAVAILABLE") from exc
            kp_request_id = "kp_" + request_id[:70]
            try:
                raw = await _call(_kp_prompt(script, snapshot, lane=lane, message=message, events=events, request_id=kp_request_id), category="rpg_kp", char_id=char_id, timeout=_KP_TIMEOUT)
                proposal_data = _extract_json(raw)
                proposal_data["request_id"] = kp_request_id
                proposal = KpProposal.model_validate(proposal_data)
            except Exception as exc:
                response = RpgTurnResponse(dream_id=dream_id, round_id=round_id, request_id=request_id, status="failed", scene_revision=core.scene_revision, error="RPG_KP_OUTPUT_INVALID")
                receipts[request_id] = {"digest": digest, "response": response.model_dump(mode="json")}
                rpg_store.save_turn_receipts(uid, dream_id, receipts, char_id=char_id)
                return response
            try:
                result = apply_proposal(uid, dream_id, proposal, expected_revision=expected_revision, char_id=char_id)
            except RpgKernelError as exc:
                response = RpgTurnResponse(dream_id=dream_id, round_id=round_id, request_id=request_id, status="failed", scene_revision=core.scene_revision, error=exc.code)
                receipts[request_id] = {"digest": digest, "response": response.model_dump(mode="json")}
                rpg_store.save_turn_receipts(uid, dream_id, receipts, char_id=char_id)
                return response
            core, events, snapshot = _load_context(uid, dream_id, char_id)
            outcome = str(result.get("outcome") or "rejected")
            resolution = _entry(lane="shared", kind="resolution", content=outcome, correlation_id=request_id, revision=core.scene_revision, branch_id=core.active_branch_id or "root")
            if not rpg_store.append_transcript(uid, dream_id, resolution, char_id=char_id):
                raise RpgKernelError("RPG_TRANSCRIPT_WRITE_FAILED")
            entries.extend([user_entry, resolution])
            dice_ids = []
            dice_rows = rpg_store.read_dice(uid, dream_id, char_id=char_id)
            dice_ids.extend(str(row.get("dice_id")) for row in dice_rows if row.get("request_id") == kp_request_id and row.get("dice_id"))
            character_reply_generated = False
            pending_check: str | None = None
            if proposal.character_should_respond:
                try:
                    from core import character_loader
                    character = character_loader.load(char_id)
                    reply = await _call(_character_prompt(character, snapshot, message=message, entries=entries), category="chat", char_id=char_id, timeout=_CHARACTER_TIMEOUT)
                    marker = parse_character_marker(reply)
                    if marker.status == "valid":
                        pending_check = marker.request.intent_text if marker.request else None
                    visible = marker.visible_text
                    if visible:
                        character_entry = _entry(lane="character", kind="character_reply", content=visible, correlation_id=request_id, revision=core.scene_revision, branch_id=core.active_branch_id or "root")
                        if not rpg_store.append_transcript(uid, dream_id, character_entry, char_id=char_id):
                            raise RpgKernelError("RPG_TRANSCRIPT_WRITE_FAILED")
                        entries.append(character_entry)
                        character_reply_generated = True
                except RpgKernelError:
                    raise
                except Exception:
                    status = "partial"
                    response = RpgTurnResponse(dream_id=dream_id, round_id=round_id, request_id=request_id, status=status, scene_revision=core.scene_revision, entries=tuple(RpgEntry.model_validate(item) for item in entries), character_reply_generated=False, dice_roll_ids=tuple(dice_ids), error="RPG_CHARACTER_GENERATION_FAILED")
                    receipts[request_id] = {"digest": digest, "response": response.model_dump(mode="json")}
                    rpg_store.save_turn_receipts(uid, dream_id, receipts, char_id=char_id)
                    return response
            if pending_check:
                check_request_id = "kp_check_" + request_id[:64]
                try:
                    raw = await _call(_kp_prompt(script, snapshot, lane="character", message=pending_check, events=events, request_id=check_request_id), category="rpg_kp", char_id=char_id, timeout=_KP_TIMEOUT)
                    check_data = _extract_json(raw)
                    check_data["request_id"] = check_request_id
                    check_proposal = KpProposal.model_validate(check_data)
                    check_result = apply_proposal(uid, dream_id, check_proposal, expected_revision=core.scene_revision, char_id=char_id)
                    core, events, snapshot = _load_context(uid, dream_id, char_id)
                    check_entry = _entry(lane="shared", kind="character_check", content=str(check_result.get("outcome") or "rejected"), correlation_id=request_id, revision=core.scene_revision, branch_id=core.active_branch_id or "root")
                    if rpg_store.append_transcript(uid, dream_id, check_entry, char_id=char_id):
                        entries.append(check_entry)
                        if check_proposal.character_should_respond:
                            from core import character_loader
                            character = character_loader.load(char_id)
                            followup = await _call(_character_prompt(character, snapshot, message=message, entries=entries, check_intent=pending_check), category="chat", char_id=char_id, timeout=_CHARACTER_TIMEOUT)
                            followup_visible = parse_character_marker(followup).visible_text
                            if followup_visible:
                                follow_entry = _entry(lane="character", kind="character_followup", content=followup_visible, correlation_id=request_id, revision=core.scene_revision, branch_id=core.active_branch_id or "root")
                                if rpg_store.append_transcript(uid, dream_id, follow_entry, char_id=char_id):
                                    entries.append(follow_entry)
                except Exception:
                    pass
            response = RpgTurnResponse(dream_id=dream_id, round_id=round_id, request_id=request_id, status="completed", scene_revision=core.scene_revision, entries=tuple(RpgEntry.model_validate(item) for item in entries), character_reply_generated=character_reply_generated, dice_roll_ids=tuple(dice_ids))
            receipts[request_id] = {"digest": digest, "response": response.model_dump(mode="json")}
            rpg_store.save_turn_receipts(uid, dream_id, receipts, char_id=char_id)
            return response
        finally:
            _INFLIGHT.discard(key)


def transcript_projection(uid: str, dream_id: str, *, char_id: str, before: str | None, limit: int) -> dict[str, Any]:
    core, health = rpg_store.load(uid, dream_id, char_id=char_id)
    if core is None or health != "ok":
        raise RpgKernelError("RPG_NOT_ACTIVE")
    rows, partial = rpg_store.read_transcript(uid, dream_id, char_id=char_id)
    branch = core.active_branch_id or "root"
    rows = [row for row in rows if row.get("branch_id", branch) == branch]
    if before:
        rows = [row for row in rows if str(row.get("entry_id")) < before]
    rows = sorted(rows, key=lambda row: (float(row.get("ts") or 0), str(row.get("entry_id"))))
    has_more = len(rows) > limit
    page = rows[-limit:] if has_more else rows
    next_before = str(page[0].get("entry_id")) if has_more and page else None
    return {"items": tuple(RpgEntry.model_validate(row) for row in page), "next_before": next_before, "has_more": has_more, "partial_read": partial, "scene_revision": core.scene_revision, "active_branch_id": branch}
