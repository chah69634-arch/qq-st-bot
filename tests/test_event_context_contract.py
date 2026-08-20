from __future__ import annotations

import pytest

from core.event_context import EventContext
from core.memory.scope import MemoryScope


def test_event_context_freezes_reality_scope_and_derives_evidence_ids():
    context = EventContext.from_ingress(
        uid="owner-a", char_id="char-a", ingress_event_id="ing-a",
        dedupe_key="dedupe-a", source="desktop_chat", channel="desktop",
        kind="user_message", actor="user",
    ).with_turn("turn-a")

    assert context.scope == MemoryScope.reality_scope("owner-a", "char-a")
    assert context.causation_id == "ing-a"
    assert context.evidence_id("user") == "turn-a:user"
    assert context.evidence_id("assistant") == "turn-a:assistant"
    assert context.to_payload()["ingress_event_id"] == "ing-a"


def test_event_context_rejects_dream_and_evidence_without_turn():
    with pytest.raises(ValueError, match="reality"):
        EventContext(
            schema_version=1,
            scope=MemoryScope.dream_scope("owner-a", "char-a", "world-a"),
            ingress_event_id="ing-a", dedupe_key="dedupe-a", source="dream",
            channel="dream", kind="message",
        )

    context = EventContext.from_ingress(
        uid="owner-a", char_id="char-a", ingress_event_id="ing-a",
        dedupe_key="dedupe-a", source="desktop", channel="desktop", kind="wake",
    )
    with pytest.raises(ValueError, match="turn_id"):
        context.evidence_id("assistant")


@pytest.mark.asyncio
async def test_perceive_result_exposes_explicit_ingress_aliases(monkeypatch):
    from core.perceive_event import PerceiveEvent, PerceiveStatus, clear_dedup_registry_for_test, receive_perceive_event
    clear_dedup_registry_for_test()
    monkeypatch.setattr("core.perceive_event._resolve_char_id", lambda _uid, _char: "char-a")
    event = PerceiveEvent(source="scheduler", uid="owner-a", channel="system", kind="trigger", require_dream_guard=False)
    first = await receive_perceive_event(event)
    second = await receive_perceive_event(event)
    assert first.status == PerceiveStatus.ACCEPTED
    assert first.ingress_event_id == first.event_id
    assert second.status == PerceiveStatus.DUPLICATE
    assert second.existing_ingress_event_id == first.ingress_event_id
