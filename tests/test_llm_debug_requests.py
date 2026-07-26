from __future__ import annotations

from types import SimpleNamespace

from core import llm_debug_requests as debug


def _paths(tmp_path):
    return SimpleNamespace(llm_debug_request_log=lambda: tmp_path / "llm_debug_requests.jsonl")


def test_debug_request_snapshots_are_disabled_by_default(tmp_path, monkeypatch):
    monkeypatch.setattr(debug, "get_paths", lambda: _paths(tmp_path))
    monkeypatch.setattr("core.config_loader.get_config", lambda: {})

    debug.append(
        provider="test", model="model", purpose="chat",
        messages=[{"role": "user", "content": "private"}], tools=None, request_kwargs={},
    )

    assert debug.query() == []


def test_debug_request_snapshot_keeps_tool_schema_but_redacts_sensitive_data(tmp_path, monkeypatch):
    monkeypatch.setattr(debug, "get_paths", lambda: _paths(tmp_path))
    monkeypatch.setattr(
        "core.config_loader.get_config",
        lambda: {"llm_debug_requests": {"enabled": True, "keep_days": 1}},
    )

    debug.append(
        provider="compat", model="test-model", purpose="chat",
        messages=[{"role": "user", "content": "please inspect", "authorization": "Bearer secret"}],
        tools=[{"function": {"name": "mcp__arcade__play", "parameters": {"type": "object"}}}],
        request_kwargs={"api_key": "should-not-persist", "image": "data:image/png;base64,very-private"},
    )

    rows = debug.query()
    assert len(rows) == 1
    assert rows[0]["tools"][0]["function"]["name"] == "mcp__arcade__play"
    assert rows[0]["messages"][0]["authorization"] == "[REDACTED]"
    assert rows[0]["request_kwargs"]["api_key"] == "[REDACTED]"
    assert rows[0]["request_kwargs"]["image"] == "[REDACTED image data URL]"
