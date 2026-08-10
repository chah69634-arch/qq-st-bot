"""Focused recovery and canonical replay coverage for Brief 173."""

import asyncio

import pytest


@pytest.mark.asyncio
async def test_persisted_running_receipt_becomes_outcome_unknown_without_rerun(sandbox):
    from core import owner_turn_receipts, owner_turn_service

    client_turn_id = "restart-turn-1"
    digest = owner_turn_receipts.request_hash(message="hello", reply_to=None, upload_ids=[])
    owner_turn_receipts.write(
        caller_label="owner-input",
        client_turn_id=client_turn_id,
        request_digest=digest,
        status="running",
    )
    calls = []

    async def executor(*_args, **_kwargs):
        calls.append(True)
        return {"reply": "must not run", "turn_id": "turn-new"}

    status, projection = await owner_turn_service.execute_idempotent_owner_turn(
        client_turn_id=client_turn_id,
        message="hello",
        reply_to=None,
        upload_ids=[],
        context=owner_turn_service.owner_input_context("owner-input"),
        executor=executor,
    )

    assert status == "interrupted_unknown"
    assert projection["status"] == "interrupted_unknown"
    assert projection["error_code"] == "execution_outcome_unknown"
    assert calls == []

    again, _ = await owner_turn_service.execute_idempotent_owner_turn(
        client_turn_id=client_turn_id,
        message="hello",
        reply_to=None,
        upload_ids=[],
        context=owner_turn_service.owner_input_context("owner-input"),
        executor=executor,
    )
    assert again == "interrupted_unknown"
    assert calls == []


@pytest.mark.asyncio
async def test_completed_replay_uses_receipt_character_after_active_switch(sandbox, monkeypatch):
    from core import config_loader, owner_turn_service
    from core.memory import short_term

    monkeypatch.setattr(
        config_loader,
        "get_config",
        lambda: {"scheduler": {"owner_id": "owner"}, "memory": {"short_term_rounds": 20}},
    )
    short_term.append(
        "owner",
        "assistant",
        "reply from character a",
        turn_id="canonical-a",
        char_id="character-a",
    )
    active = {"value": "character-a"}
    monkeypatch.setattr(owner_turn_service, "_canonical_character_id", lambda: active["value"])

    async def executor(*_args, **_kwargs):
        await asyncio.sleep(0)
        return {"reply": "reply from character a", "turn_id": "canonical-a"}

    context = owner_turn_service.owner_input_context("owner-input")
    first, _ = await owner_turn_service.execute_idempotent_owner_turn(
        client_turn_id="switch-turn-1",
        message="hello",
        reply_to=None,
        upload_ids=[],
        context=context,
        executor=executor,
    )
    assert first == "completed"

    active["value"] = "character-b"
    replay, result = await owner_turn_service.execute_idempotent_owner_turn(
        client_turn_id="switch-turn-1",
        message="hello",
        reply_to=None,
        upload_ids=[],
        context=context,
        executor=executor,
    )
    assert replay == "completed_replay"
    assert result["turn_id"] == "canonical-a"
    assert result["reply"] == "reply from character a"
