"""Dream exit lifecycle ledger stays bounded and text-free."""
from __future__ import annotations


def test_lifecycle_upsert_is_safe_and_tracks_send_attempt(sandbox):
    from core.dream.exit_observability import get_record, list_records, record

    record(
        "owner",
        "dream-1",
        char_id="dreamer",
        lifecycle="waiting_afterglow",
        reason_code="afterglow_not_ready",
    )
    record(
        "owner",
        "dream-1",
        char_id="dreamer",
        lifecycle="blocked",
        reason_code="dnd",
    )
    sent = record("owner", "dream-1", char_id="dreamer", lifecycle="sent")

    assert sent["lifecycle"] == "sent"
    assert sent["reason_code"] == ""
    assert sent["attempts"] == 2
    rows = list_records(char_id="dreamer")
    assert len(rows) == 1
    assert rows[0]["dream_id"] == "dream-1"
    assert "letter" not in rows[0]
    assert get_record("missing", char_id="dreamer") is None


def test_postcard_eligibility_requires_complete_sandbox_dream():
    from core.dream.postcard import evaluate_postcard_eligibility

    turns = [{"role": "assistant", "content": "reply"}] * 5
    assert evaluate_postcard_eligibility(
        dream_id="d",
        dream_mode="scenario",
        completion="complete",
        turns=turns,
        existing_entries=[],
    ).reason_code == "not_solo_sandbox"
    assert evaluate_postcard_eligibility(
        dream_id="d",
        dream_mode="sandbox",
        completion="interrupted",
        turns=turns,
        existing_entries=[],
    ).reason_code == "interrupted"
    assert evaluate_postcard_eligibility(
        dream_id="d",
        dream_mode="sandbox",
        completion="complete",
        turns=turns,
        existing_entries=[],
    ).eligible is True
