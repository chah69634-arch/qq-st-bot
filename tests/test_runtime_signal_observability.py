from __future__ import annotations


def test_runtime_signal_snapshot_is_process_local_aggregated_and_redacted():
    from core.runtime_signal_observability import _reset_for_tests, record, snapshot

    _reset_for_tests()
    assert record(
        category="model_quality",
        code="emotion_output_invalid",
        status="attention",
        context={
            "purpose": "detect_emotion",
            "reason": "empty",
            "token": "must-not-appear",
            "api_key": "must-not-appear",
            "content": "must-not-appear",
            "uid": "must-not-appear",
            "path": "must-not-appear",
        },
    )
    assert not record(
        category="model_quality",
        code="emotion_output_invalid",
        status="attention",
        context={"purpose": "detect_emotion", "reason": "empty"},
    )

    payload = snapshot()
    assert payload["scope"] == "process"
    assert payload["summary"] == {"ok": 0, "attention": 1}
    signal = payload["signals"]
    assert len(signal) == 1
    assert signal[0]["count"] == 2
    assert signal[0]["unique_contexts"] == 1
    assert signal[0]["latest_context"] == {"purpose": "detect_emotion", "reason": "empty"}


def test_runtime_signals_endpoint_requires_state_read_and_returns_snapshot(sandbox, monkeypatch):
    from fastapi.testclient import TestClient
    from core.runtime_signal_observability import _reset_for_tests, record

    secret = "runtime-signals-test-admin-secret"
    monkeypatch.setattr("admin.auth.get_admin_secret", lambda: secret)
    _reset_for_tests()
    record(
        category="boundary_invariants",
        code="midterm_write_skipped_for_isolated_source",
        status="ok",
        context={"source": "dream_echo"},
    )

    from admin.admin_server import app

    client = TestClient(app, raise_server_exceptions=False)
    assert client.get("/observability/runtime-signals").status_code == 401
    response = client.get(
        "/observability/runtime-signals",
        headers={"Authorization": f"Bearer {secret}"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["scope"] == "process"
    assert payload["signals"][0]["code"] == "midterm_write_skipped_for_isolated_source"
