"""Brief 169: text-free, bounded Scenario progress audit ledger."""

import json


def test_scenario_progress_audit_is_bounded_and_redacted(sandbox):
    from core.dream.scenario_progress_audit import list_records, record

    for index in range(205):
        record(
            f"dream_{index}",
            char_id="audit_char",
            turn_index=index,
            current_stage_id="opening",
            control_status="valid",
            control_version=2,
            matched_exit_ids=["E1", "not-an-id"],
            blocked_ids=["B1", "B9999"],
            valid_exit_sign_count=1,
            unknown_exit_sign_count=1,
            unknown_blocked_event_count=1,
            disposition="advanced",
            detail_reason="not-a-safe-reason",
            from_stage_id="opening",
            to_stage_id="next_stage",
            stall_turns=2,
            recovery_pending=True,
        )

    rows = list_records(char_id="audit_char", limit=500)
    assert len(rows) == 200
    assert rows[0]["dream_id"] == "dream_204"
    assert rows[-1]["dream_id"] == "dream_5"
    assert rows[0]["matched_exit_ids"] == ["E1"]
    assert rows[0]["blocked_ids"] == ["B1"]
    assert rows[0]["detail_reason"] == ""
    forbidden = {"user_message", "reply", "prompt", "exit_sign", "private_truth", "path"}
    assert not forbidden.intersection(rows[0])

    path = sandbox.dreams_scenario_progress_audit_path(char_id="audit_char")
    persisted = json.loads(path.read_text(encoding="utf-8"))
    assert len(persisted) == 200


def test_scenario_progress_audit_write_is_fail_open(monkeypatch):
    import core.dream.scenario_progress_audit as audit

    monkeypatch.setattr(audit, "get_paths", lambda: (_ for _ in ()).throw(OSError("blocked")))
    row = audit.record("dream_fail_open", disposition="no_progress")
    assert row["dream_id"] == "dream_fail_open"
    assert audit.list_records(dream_id="dream_fail_open") == []


def test_reconciler_audit_is_text_free_and_has_safe_transition_fields(sandbox):
    from core.dream.scenario_progress_audit import list_records, record_reconciler

    record_reconciler(
        "dream_reconcile_audit",
        char_id="audit_reconciler",
        assistant_turn_id="dream_reconcile_audit:assistant:1",
        trigger="control_missing",
        status="completed",
        decision="advance_next",
        applied=True,
        from_stage_id="opening",
        to_stage_id="next_stage",
        expected_state_version=7,
        state_version=8,
        state_version_match=True,
        duration_ms=123,
        failure_code="",
        effective_profile="default",
        preset_name="intent-preset",
        route_source="intent_fallback",
    )
    row = list_records(char_id="audit_reconciler", limit=1)[0]
    assert row["record_kind"] == "reconciler"
    assert row["reconciler_applied"] is True
    assert row["reconciler_from_stage_id"] == "opening"
    assert row["reconciler_to_stage_id"] == "next_stage"
    assert row["reconciler_state_version"] == 8
    forbidden = {"user_message", "reply", "prompt", "private_truth", "base_url", "model"}
    assert not forbidden.intersection(row)
