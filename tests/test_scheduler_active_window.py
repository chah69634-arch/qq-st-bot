import json
import sys
import time
from types import SimpleNamespace

import pytest


class _FakePipeline:
    character = type("_C", (), {"name": "TestChar"})()

    def _current_reality_scope(self, uid):
        return type("Scope", (), {"character_id": "yexuan"})()

    async def fetch_context(self, uid, query, **kwargs):
        return {}

    def build_prompt(self, uid, prompt, context, **kwargs):
        return [{"role": "user", "content": prompt}], {}

    async def run_llm(self, messages, **kwargs):
        return "reply"


def _install_fastapi_stub(monkeypatch):
    class HTTPException(Exception):
        def __init__(self, status_code=500, detail=""):
            super().__init__(detail)
            self.status_code = status_code
            self.detail = detail

    class APIRouter:
        def get(self, *args, **kwargs):
            return lambda fn: fn

        def post(self, *args, **kwargs):
            return lambda fn: fn

        def put(self, *args, **kwargs):
            return lambda fn: fn

        def delete(self, *args, **kwargs):
            return lambda fn: fn

    def marker(default=None, *args, **kwargs):
        return default

    class HTTPBearer:
        def __init__(self, *args, **kwargs):
            pass

        def __call__(self):
            return None

    class HTTPAuthorizationCredentials:
        credentials = ""

    monkeypatch.setitem(
        sys.modules,
        "fastapi",
        SimpleNamespace(
            APIRouter=APIRouter,
            Body=marker,
            Depends=marker,
            File=marker,
            Form=marker,
            HTTPException=HTTPException,
            Query=marker,
            Request=object,
            UploadFile=object,
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "fastapi.security",
        SimpleNamespace(
            HTTPBearer=HTTPBearer,
            HTTPAuthorizationCredentials=HTTPAuthorizationCredentials,
        ),
    )


def _install_ui_transport_stubs(monkeypatch):
    """Keep this scheduler test outside the concrete WebSocket transports."""
    import channels

    async def noop(*args, **kwargs):
        return None

    desktop_ws = SimpleNamespace(
        is_connected=lambda: False,
        _new_msg_id=lambda: "test-stream-message",
        push_message=noop,
        push_segments=noop,
    )
    ui_push = SimpleNamespace(
        any_connected=lambda: False,
        push_stream_start=noop,
        push_stream_delta=noop,
        push_stream_end=noop,
    )

    monkeypatch.setitem(sys.modules, "channels.desktop_ws", desktop_ws)
    monkeypatch.setitem(sys.modules, "channels.ui_push", ui_push)
    # `from channels import ...` can reuse attributes cached on the package by
    # an earlier test, so replace those attributes as well as sys.modules.
    monkeypatch.setattr(channels, "desktop_ws", desktop_ws, raising=False)
    monkeypatch.setattr(channels, "ui_push", ui_push, raising=False)


@pytest.mark.asyncio
async def test_owner_chat_turn_marks_user_active(monkeypatch):
    _install_fastapi_stub(monkeypatch)
    _install_ui_transport_stubs(monkeypatch)
    from admin.routers import chat
    from core.scheduler import loop

    turns = []

    async def fake_record_assistant_turn(**kwargs):
        turns.append(kwargs)
        return SimpleNamespace(
            fanout_failures={},
            emotion="neutral",
            turn_id="t1",
            written_to_memory=True,
        )

    monkeypatch.setattr(loop, "_last_user_message_time", 0.0)
    monkeypatch.setattr("core.pipeline_registry.get", lambda: _FakePipeline())
    monkeypatch.setattr("core.config_loader.get_config", lambda: {"scheduler": {"owner_id": "u1"}})
    async def fake_probe(message, user_id, *, char_id="yexuan", provenance_channel=None):
        return ""

    monkeypatch.setattr(chat, "_probe_and_execute_tools", fake_probe)
    monkeypatch.setattr("channels.registry.get", lambda name: None)
    monkeypatch.setattr("core.turn_sink.record_assistant_turn", fake_record_assistant_turn)

    await chat.run_owner_chat_turn("hello", "desktop")

    assert loop._user_active_recently()
    assert turns and turns[0]["user_text"] == "hello"


@pytest.mark.asyncio
async def test_execute_prompt_blocked_send_does_not_mark_or_after_send(monkeypatch):
    from core.scheduler import execution, loop

    marks = []
    after_send = []

    async def blocked_send(prompt, search_query="", trigger_name="", **kwargs):
        return None

    monkeypatch.setattr(loop, "_pipeline_send", blocked_send)
    monkeypatch.setattr(loop, "_mark", lambda name: marks.append(name))

    result = await execution.execute_prompt(
        trigger_name="random_message",
        prompt_factory=lambda: "prompt",
        dry_run=False,
        would_mark=["random_message"],
        after_send=lambda: after_send.append("called"),
    )

    assert result.sent is False
    assert marks == []
    assert after_send == []


@pytest.mark.asyncio
async def test_execute_prompt_dry_run_still_records(monkeypatch, sandbox):
    from core.scheduler import execution

    result = await execution.execute_prompt(
        trigger_name="random_message",
        prompt_factory=lambda: "prompt",
        dry_run=True,
        would_mark=["random_message"],
        would_mark_done=["r1"],
    )

    assert result.sent is False
    rows = sandbox.execute_dryrun_log().read_text(encoding="utf-8").splitlines()
    assert rows
    row = json.loads(rows[-1])
    assert row["trigger_name"] == "random_message"
    assert row["would_mark_done"] == ["r1"]


@pytest.mark.asyncio
async def test_pipeline_send_high_priority_exempt_from_active_window(monkeypatch):
    from core.scheduler import loop

    recorded = []

    async def fake_record_assistant_turn(**kwargs):
        recorded.append(kwargs)
        return SimpleNamespace(fanout_failures={})

    monkeypatch.setattr("core.pipeline_registry.get", lambda: _FakePipeline())
    monkeypatch.setattr(loop, "_owner_id", lambda: "u1")
    monkeypatch.setattr(loop, "_last_user_message_time", time.time())
    monkeypatch.setattr("core.scheduler.triggers.birthday._is_birthday_period", lambda: False)
    monkeypatch.setattr("core.turn_sink.record_assistant_turn", fake_record_assistant_turn)

    result = await loop._pipeline_send("prompt", trigger_name="hr_critical")

    assert result == "reply"
    assert recorded and recorded[0]["trigger_name"] == "hr_critical"
