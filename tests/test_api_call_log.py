from types import SimpleNamespace
from datetime import datetime, timedelta

from core import api_call_log


def test_api_call_log_is_fail_open_and_returns_newest_filtered_rows(tmp_path, monkeypatch):
    ledger = tmp_path / "api_calls.jsonl"
    monkeypatch.setattr(
        api_call_log,
        "get_paths",
        lambda: SimpleNamespace(api_call_log=lambda: ledger),
    )

    api_call_log.append(
        caller="llm_client",
        purpose="chat",
        provider="openai",
        model="test-model",
        duration_ms=15,
        ok=True,
    )
    api_call_log.append(
        caller="web_search",
        purpose="search",
        provider="ddgs",
        model="text",
        duration_ms=20,
        ok=False,
        output_hint="TimeoutError",
        request_id="request-123",
        audit_id="audit-123",
    )

    rows, grouped = api_call_log.query(provider="ddgs")

    assert len(rows) == 1
    assert rows[0]["caller"] == "web_search"
    assert rows[0]["duration_ms"] == 20
    assert rows[0]["output_hint"] == "TimeoutError"
    assert rows[0]["request_id"] == "request-123"
    assert rows[0]["audit_id"] == "audit-123"
    assert grouped == {"ddgs": 1}


def test_api_call_log_never_persists_long_output_hint(tmp_path, monkeypatch):
    ledger = tmp_path / "api_calls.jsonl"
    monkeypatch.setattr(
        api_call_log,
        "get_paths",
        lambda: SimpleNamespace(api_call_log=lambda: ledger),
    )

    api_call_log.append(
        caller="embedding",
        purpose="encode",
        provider="openai_compat",
        model="embedding-model",
        duration_ms=-1,
        ok=False,
        output_hint="x" * 300,
    )

    rows, _ = api_call_log.query()

    assert rows[0]["duration_ms"] == 0
    assert len(rows[0]["output_hint"]) == 120


def test_api_call_log_uses_daily_files_and_prunes_expired_days(tmp_path):
    ledger = tmp_path / "api_calls.jsonl"
    today = datetime(2026, 7, 22).timestamp()
    old_day = (datetime(2026, 7, 22) - timedelta(days=7)).strftime("%Y-%m-%d")
    old_path = tmp_path / f"api_calls-{old_day}.jsonl"
    old_path.write_text('{"ts": 1}\n', encoding="utf-8")

    today_path = api_call_log._daily_path(ledger, today)
    assert today_path.name == "api_calls-2026-07-22.jsonl"

    api_call_log._prune_daily_logs(ledger, today)

    assert not old_path.exists()
