"""Append-only clarification, retcon, and branch commands for RPG Dream."""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import replace

from core.dream import rpg_store
from core.dream.rpg_engine import RpgKernelError, recover_existing_event, session_lock
from core.dream.rpg_projection import events_for_branch

def _digest(kind: str, target_round_id: str, text: str) -> str:
    raw = json.dumps({"kind": kind, "target_round_id": target_round_id, "text": text}, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def _command(
    uid: str, dream_id: str, *, char_id: str, request_id: str, expected_revision: int,
    target_round_id: str, kind: str, text: str,
) -> dict:
    if kind not in {"clarify", "retcon", "branch"} or not request_id or len(request_id) > 80:
        raise RpgKernelError("RPG_INVALID_CORRECTION")
    if not isinstance(expected_revision, int) or expected_revision < 0 or not target_round_id:
        raise RpgKernelError("RPG_INVALID_REVISION")
    if not text or len(text) > 500:
        raise RpgKernelError("RPG_INVALID_CORRECTION")
    with session_lock(uid, dream_id, char_id):
        core, health = rpg_store.load(uid, dream_id, char_id=char_id)
        if core is None or health != "ok":
            raise RpgKernelError("RPG_SESSION_UNAVAILABLE")
        events, events_health = rpg_store.read_events_with_health(uid, dream_id, char_id=char_id)
        if events_health == "invalid":
            rpg_store.mark_uncertain(uid, dream_id, char_id=char_id, error_code="RPG_LEDGER_INVALID")
            raise RpgKernelError("RPG_LEDGER_INVALID")
        digest = _digest(kind, target_round_id, text)
        prior = next((event for event in events if event.get("request_id") == request_id), None)
        if prior:
            if prior.get("request_digest") != digest:
                rpg_store.record_kernel_stat(uid, dream_id, "recovery_conflict_count", char_id=char_id)
                raise RpgKernelError("RPG_REQUEST_CONFLICT")
            recover_existing_event(uid, dream_id, core, prior, events, char_id=char_id)
            return {"ok": True, "event_id": prior.get("event_id"), "revision": prior.get("revision"), "idempotent": True}
        if core.status != "active":
            raise RpgKernelError("RPG_SESSION_UNAVAILABLE")
        if core.scene_revision != expected_revision:
            raise RpgKernelError("RPG_REVISION_CONFLICT")
        old = next((event for event in events_for_branch(events, core.active_branch_id or "root") if event.get("round_id") == target_round_id), None)
        if old is None:
            raise RpgKernelError("RPG_TARGET_ROUND_NOT_FOUND")
        branch_id = core.active_branch_id or "root"
        payload = {"kind": kind, "target_round_id": target_round_id, "text": text}
        if kind in {"retcon", "branch"}:
            new_branch = "branch_" + uuid.uuid4().hex
            payload.update({"parent_branch_id": branch_id, "new_branch_id": new_branch, "base_seq": max(0, int(old["seq"]) - 1)})
            branch_id = new_branch
        updated = replace(core, active_branch_id=branch_id, next_event_seq=core.next_event_seq + 1,
                          scene_revision=core.scene_revision + 1, updated_at=time.time())
        event = {
            "schema_version": 1, "event_id": "evt_" + uuid.uuid4().hex, "dream_id": dream_id,
            "round_id": target_round_id, "branch_id": core.active_branch_id or "root", "seq": core.next_event_seq,
            "ts": time.time(), "event_type": "clarification" if kind == "clarify" else "branch_created",
            "causation_id": "cause_" + uuid.uuid4().hex, "request_id": request_id, "request_digest": digest,
            "payload": payload, "projections": {"public": [], "player": [], "character": [], "kp_private": []},
            "scene_updates": [], "revision": updated.scene_revision,
            "core_after": {"active_branch_id": updated.active_branch_id, "active_round_id": updated.active_round_id,
                           "round_status": updated.round_status, "next_round_seq": updated.next_round_seq,
                           "next_event_seq": updated.next_event_seq, "scene_revision": updated.scene_revision},
        }
        if not rpg_store.append_event(uid, dream_id, event, char_id=char_id):
            raise RpgKernelError("RPG_EVENT_WRITE_FAILED")
        saved, reason = rpg_store.save(updated, expected_revision=expected_revision)
        if not saved:
            rpg_store.mark_uncertain(uid, dream_id, char_id=char_id, error_code="RPG_CORE_" + reason.upper())
            raise RpgKernelError("RPG_COMMIT_UNCERTAIN")
        from core.dream.rpg_engine import rebuild_snapshot
        rebuild_snapshot(uid, dream_id, char_id=char_id)
        return {"ok": True, "event_id": event["event_id"], "revision": updated.scene_revision, "branch_id": branch_id, "idempotent": False}


def clarify(uid: str, dream_id: str, target_round_id: str, text: str, *, request_id: str, expected_revision: int, char_id: str) -> dict:
    return _command(uid, dream_id, char_id=char_id, request_id=request_id, expected_revision=expected_revision, target_round_id=target_round_id, kind="clarify", text=text)


def retcon(uid: str, dream_id: str, target_round_id: str, reason: str, *, request_id: str, expected_revision: int, char_id: str) -> dict:
    return _command(uid, dream_id, char_id=char_id, request_id=request_id, expected_revision=expected_revision, target_round_id=target_round_id, kind="retcon", text=reason)


def branch(uid: str, dream_id: str, target_round_id: str, reason: str, *, request_id: str, expected_revision: int, char_id: str) -> dict:
    return _command(uid, dream_id, char_id=char_id, request_id=request_id, expected_revision=expected_revision, target_round_id=target_round_id, kind="branch", text=reason)
