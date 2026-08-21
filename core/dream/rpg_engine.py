"""Deterministic, LLM-free adjudication kernel for RPG Dream sessions."""

from __future__ import annotations

import hashlib
import json
import threading
import time
import uuid
from collections import defaultdict
from dataclasses import replace
from typing import Any

from pydantic import ValidationError

from core.dream.rpg_dice import generate_seed, resolve_roll
from core.dream.rpg_models import KpProposal, RpgCore
from core.dream.rpg_projection import derive_snapshot
from core.dream import rpg_store

_LOCKS: dict[tuple[str, str, str], threading.RLock] = defaultdict(threading.RLock)


class RpgKernelError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def session_lock(uid: str, dream_id: str, char_id: str) -> threading.RLock:
    return _LOCKS[(uid, dream_id, char_id)]


def _digest(proposal: KpProposal) -> str:
    raw = json.dumps(proposal.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def _validate_scene(core: RpgCore, scene_id: str | None) -> None:
    if scene_id is None:
        return
    from core.dream.scenario_loader import load_script
    try:
        script = load_script(core.script_id)
    except (FileNotFoundError, ValueError) as exc:
        raise RpgKernelError("RPG_SCRIPT_UNAVAILABLE") from exc
    allowed = {str(stage.get("id")) for stage in script.get("stages") or [] if isinstance(stage, dict)}
    if scene_id not in allowed:
        raise RpgKernelError("RPG_INVALID_SCENE_REFERENCE")


_KNOWLEDGE_TRANSITIONS = {
    "unknown": {"unknown", "suspected", "known", "misbelieved"},
    "suspected": {"suspected", "known", "misbelieved"},
    "known": {"known"},
    "misbelieved": {"misbelieved", "known"},
}


def _validate_knowledge_transitions(core: RpgCore, proposal: KpProposal, events: list[dict[str, Any]]) -> None:
    """Reject silent loss of character knowledge before a branch is resolved."""
    current = derive_snapshot(events, active_branch_id=core.active_branch_id, revision=core.scene_revision)
    facts = current["character_knowledge"]
    for branch in proposal.outcome_branches.values():
        for fact in branch.projections.character:
            previous = (facts.get(fact.fact_id) or {}).get("knowledge", "unknown")
            next_state = fact.knowledge or "unknown"
            if next_state not in _KNOWLEDGE_TRANSITIONS.get(previous, set()):
                raise RpgKernelError("RPG_KNOWLEDGE_CONFLICT")


def _event(*, core: RpgCore, proposal: KpProposal, outcome: str, causation_id: str, proposal_digest: str, core_after: RpgCore) -> dict[str, Any]:
    branch = proposal.outcome_branches.get(outcome)
    if branch is None:
        projections, scene_updates = {}, []
    else:
        projections, scene_updates = branch.projections.model_dump(mode="json"), [item.model_dump() for item in branch.scene_updates]
    return {
        "schema_version": 1,
        "event_id": "evt_" + uuid.uuid4().hex,
        "dream_id": core.dream_id,
        "round_id": core.active_round_id or f"round_{core.next_round_seq}",
        "branch_id": core.active_branch_id or "root",
        "seq": core.next_event_seq,
        "ts": time.time(),
        "event_type": "resolution",
        "causation_id": causation_id,
        "request_id": proposal.request_id,
        "request_digest": proposal_digest,
        "payload": {
            "decision": proposal.decision,
            "check_type": proposal.check_type,
            "reason_code": proposal.reason_code,
            "outcome": outcome,
            "character_should_respond": proposal.character_should_respond,
        },
        "projections": projections,
        "scene_updates": scene_updates,
        "core_after": {
            "active_branch_id": core_after.active_branch_id,
            "active_round_id": core_after.active_round_id,
            "round_status": core_after.round_status,
            "next_round_seq": core_after.next_round_seq,
            "next_event_seq": core_after.next_event_seq,
            "scene_revision": core_after.scene_revision,
        },
    }


def _result(event: dict[str, Any], *, idempotent: bool = False) -> dict[str, Any]:
    payload = event.get("payload") or {}
    return {
        "ok": True,
        "event_id": event.get("event_id"),
        "round_id": event.get("round_id"),
        "branch_id": event.get("branch_id"),
        "revision": event.get("revision"),
        "outcome": payload.get("outcome"),
        "decision": payload.get("decision"),
        "idempotent": idempotent,
    }


def _find_request(events: list[dict[str, Any]], request_id: str) -> dict[str, Any] | None:
    return next((event for event in events if event.get("request_id") == request_id), None)


def _restore_core_after_event(core: RpgCore, event: dict[str, Any]) -> RpgCore | None:
    data = event.get("core_after")
    if not isinstance(data, dict):
        return None
    try:
        revision = data["scene_revision"]
        next_round = data["next_round_seq"]
        next_event = data["next_event_seq"]
    except KeyError:
        return None
    if not all(isinstance(value, int) for value in (revision, next_round, next_event)):
        return None
    if revision < 0 or next_round < 1 or next_event < 1 or event.get("revision") != revision:
        return None
    branch = data.get("active_branch_id")
    active_round = data.get("active_round_id")
    round_status = data.get("round_status")
    if branch is not None and not isinstance(branch, str):
        return None
    if active_round is not None and not isinstance(active_round, str):
        return None
    if not isinstance(round_status, str) or not round_status:
        return None
    return replace(
        core,
        status="active",
        active_branch_id=branch,
        active_round_id=active_round,
        round_status=round_status,
        next_round_seq=next_round,
        next_event_seq=next_event,
        scene_revision=revision,
        updated_at=time.time(),
    )


def recover_existing_event(
    uid: str, dream_id: str, core: RpgCore, event: dict[str, Any], events: list[dict[str, Any]], *, char_id: str,
) -> RpgCore:
    """Finish a core write after its append-only event survived a crash."""
    event_revision = event.get("revision")
    if not isinstance(event_revision, int):
        rpg_store.mark_uncertain(uid, dream_id, char_id=char_id, error_code="RPG_EVENT_INVALID")
        raise RpgKernelError("RPG_COMMIT_UNCERTAIN")
    if core.scene_revision >= event_revision:
        return core
    if core.scene_revision + 1 != event_revision or event.get("seq") != core.next_event_seq:
        rpg_store.mark_uncertain(uid, dream_id, char_id=char_id, error_code="RPG_EVENT_CURSOR_CONFLICT")
        raise RpgKernelError("RPG_COMMIT_UNCERTAIN")
    recovered = _restore_core_after_event(core, event)
    if recovered is None or not rpg_store.save(recovered, expected_revision=core.scene_revision)[0]:
        rpg_store.mark_uncertain(uid, dream_id, char_id=char_id, error_code="RPG_EVENT_RECOVERY_FAILED")
        raise RpgKernelError("RPG_COMMIT_UNCERTAIN")
    _commit_snapshot(recovered, events)
    return recovered


def _commit_snapshot(core: RpgCore, events: list[dict[str, Any]]) -> bool:
    snapshot = derive_snapshot(events, active_branch_id=core.active_branch_id, revision=core.scene_revision)
    from core.safe_write import safe_write_json
    return safe_write_json(rpg_store.snapshot_path(core.owner_uid, core.dream_id, char_id=core.char_id), snapshot)


def apply_proposal(
    uid: str,
    dream_id: str,
    proposal: KpProposal | dict[str, Any],
    *,
    expected_revision: int,
    char_id: str,
) -> dict[str, Any]:
    """Validate and apply one proposal. This is deliberately not an HTTP endpoint."""
    try:
        proposal = proposal if isinstance(proposal, KpProposal) else KpProposal.model_validate(proposal)
    except ValidationError as exc:
        rpg_store.record_kernel_stat(uid, dream_id, "invalid_proposal_count", char_id=char_id)
        raise RpgKernelError("RPG_INVALID_PROPOSAL") from exc
    if not isinstance(expected_revision, int) or expected_revision < 0:
        raise RpgKernelError("RPG_INVALID_REVISION")
    with session_lock(uid, dream_id, char_id):
        core, health = rpg_store.load(uid, dream_id, char_id=char_id)
        if core is None or health != "ok":
            raise RpgKernelError("RPG_SESSION_UNAVAILABLE")
        digest = _digest(proposal)
        receipts, receipts_health = rpg_store.load_receipts_with_health(uid, dream_id, char_id=char_id)
        events, events_health = rpg_store.read_events_with_health(uid, dream_id, char_id=char_id)
        dice, dice_health = rpg_store.read_dice_with_health(uid, dream_id, char_id=char_id)
        if "invalid" in {receipts_health, events_health, dice_health}:
            rpg_store.mark_uncertain(uid, dream_id, char_id=char_id, error_code="RPG_LEDGER_INVALID")
            raise RpgKernelError("RPG_LEDGER_INVALID")
        receipt = receipts.get(proposal.request_id)
        existing = _find_request(events, proposal.request_id)
        if receipt and receipt.get("proposal_digest") != digest:
            rpg_store.record_kernel_stat(uid, dream_id, "recovery_conflict_count", char_id=char_id)
            raise RpgKernelError("RPG_REQUEST_CONFLICT")
        if existing:
            if existing.get("request_digest") != digest:
                rpg_store.record_kernel_stat(uid, dream_id, "recovery_conflict_count", char_id=char_id)
                raise RpgKernelError("RPG_REQUEST_CONFLICT")
            core = recover_existing_event(uid, dream_id, core, existing, events, char_id=char_id)
            if receipt and receipt.get("status") != "committed":
                receipts[proposal.request_id] = {**receipt, "status": "committed", "event_id": existing.get("event_id")}
                rpg_store.save_receipts(uid, dream_id, receipts, char_id=char_id)
            return _result(existing, idempotent=True)
        if core.status != "active":
            raise RpgKernelError("RPG_SESSION_UNAVAILABLE")
        if receipt and receipt.get("status") == "committed":
            rpg_store.mark_uncertain(uid, dream_id, char_id=char_id, error_code="RPG_RECEIPT_EVENT_MISSING")
            raise RpgKernelError("RPG_COMMIT_UNCERTAIN")
        if core.scene_revision != expected_revision:
            raise RpgKernelError("RPG_REVISION_CONFLICT")
        _validate_scene(core, proposal.scene_id)
        _validate_knowledge_transitions(core, proposal, events)

        receipt = receipt or {"status": "pending", "proposal_digest": digest, "kind": "proposal", "created_at": time.time()}
        outcome = "rejected"
        dice_record: dict[str, Any] | None = None
        if proposal.decision == "roll":
            seed = receipt.get("seed")
            nonce = receipt.get("nonce")
            if not isinstance(seed, str) or not isinstance(nonce, str):
                seed, nonce = generate_seed()
                receipt = {**receipt, "seed": seed, "nonce": nonce}
            rolled = resolve_roll(proposal.roll_spec, seed=seed, nonce=nonce)  # type: ignore[arg-type]
            outcome = rolled.outcome
            prior_dice = next((item for item in dice if item.get("request_id") == proposal.request_id), None)
            if prior_dice is not None:
                # The JSONL parser restores the tuple-valued faces as a list.
                audit = json.loads(json.dumps(rolled.audit_dict()))
                if prior_dice.get("proposal_digest") != digest or any(prior_dice.get(key) != value for key, value in audit.items()):
                    rpg_store.mark_uncertain(uid, dream_id, char_id=char_id, error_code="RPG_DICE_RECEIPT_CONFLICT")
                    raise RpgKernelError("RPG_COMMIT_UNCERTAIN")
            else:
                dice_record = {
                    "schema_version": 1, "dice_id": "dice_" + uuid.uuid4().hex,
                    "dream_id": dream_id, "round_id": core.active_round_id or f"round_{core.next_round_seq}",
                    "branch_id": core.active_branch_id or "root", "request_id": proposal.request_id,
                    "proposal_digest": digest, "ts": time.time(), "roll_spec": proposal.roll_spec.model_dump(),
                    **rolled.audit_dict(),
                }
            receipt = {**receipt, "outcome": outcome}
        elif proposal.decision == "automatic_success":
            outcome = "success"
        elif proposal.decision == "automatic_failure":
            outcome = "failure"
        receipts[proposal.request_id] = receipt
        if not rpg_store.save_receipts(uid, dream_id, receipts, char_id=char_id):
            raise RpgKernelError("RPG_RECEIPT_WRITE_FAILED")

        if dice_record:
            if not rpg_store.append_dice(uid, dream_id, dice_record, char_id=char_id):
                raise RpgKernelError("RPG_DICE_WRITE_FAILED")
        updated = replace(core, active_branch_id=core.active_branch_id or "root", active_round_id=None,
                          round_status="idle", next_round_seq=core.next_round_seq + 1,
                          next_event_seq=core.next_event_seq + 1, scene_revision=core.scene_revision + 1,
                          updated_at=time.time())
        event = _event(core=core, proposal=proposal, outcome=outcome, causation_id="cause_" + uuid.uuid4().hex, proposal_digest=digest, core_after=updated)
        event["revision"] = updated.scene_revision
        if not rpg_store.append_event(uid, dream_id, event, char_id=char_id):
            raise RpgKernelError("RPG_EVENT_WRITE_FAILED")
        saved, save_health = rpg_store.save(updated, expected_revision=expected_revision)
        if not saved:
            rpg_store.mark_uncertain(uid, dream_id, char_id=char_id, error_code="RPG_CORE_" + save_health.upper())
            raise RpgKernelError("RPG_COMMIT_UNCERTAIN")
        _commit_snapshot(updated, events + [event])
        receipts[proposal.request_id] = {**receipt, "status": "committed", "event_id": event["event_id"], "revision": updated.scene_revision}
        rpg_store.save_receipts(uid, dream_id, receipts, char_id=char_id)
        return _result(event)


def rebuild_snapshot(uid: str, dream_id: str, *, char_id: str) -> dict[str, Any]:
    core, health = rpg_store.load(uid, dream_id, char_id=char_id)
    if core is None or health != "ok":
        raise RpgKernelError("RPG_SESSION_UNAVAILABLE")
    events, events_health = rpg_store.read_events_with_health(uid, dream_id, char_id=char_id)
    if events_health == "invalid":
        rpg_store.mark_uncertain(uid, dream_id, char_id=char_id, error_code="RPG_LEDGER_INVALID")
        raise RpgKernelError("RPG_LEDGER_INVALID")
    snapshot = derive_snapshot(events, active_branch_id=core.active_branch_id, revision=core.scene_revision)
    from core.safe_write import safe_write_json
    if not safe_write_json(rpg_store.snapshot_path(uid, dream_id, char_id=char_id), snapshot):
        raise RpgKernelError("RPG_SNAPSHOT_WRITE_FAILED")
    return snapshot
