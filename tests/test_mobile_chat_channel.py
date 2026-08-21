"""Contract tests for the separate mobile reality-chat endpoint."""

import inspect
from types import SimpleNamespace

import pytest


async def test_mobile_chat_uses_mobile_provenance_and_durable_mirror(monkeypatch):
    from admin.routers import chat, mobile

    calls = []
    notified = []

    async def fake_owner_turn(message, provenance_channel, **kwargs):
        calls.append((message, provenance_channel, kwargs))
        return {"reply": "收到", "turn_id": "turn-mobile", "msg_id": "turn-mobile"}

    monkeypatch.setattr(chat, "run_owner_chat_turn", fake_owner_turn)
    monkeypatch.setattr(chat, "_check_reality_not_in_dream", lambda uid: None)
    monkeypatch.setattr(
        "core.config_loader.get_config",
        lambda: {"scheduler": {"owner_id": "owner"}},
    )
    monkeypatch.setattr(
        "core.scheduler.sensor_events.notify_chat_happened",
        lambda: notified.append(True),
    )

    result = await mobile.mobile_chat(
        {"message": "你好", "reply_to": {"text": "上一条", "ts": 1}},
        _auth=True,
    )

    assert result["msg_id"] == "turn-mobile"
    assert notified == [True]
    assert calls == [
        (
            "你好",
            "mobile",
            {
                "live_origin_channel": "mobile",
                "durable_mobile_mirror": True,
                "reply_to": {"text": "上一条", "ts": 1},
            },
        )
    ]


async def test_desktop_chat_keeps_desktop_provenance(monkeypatch):
    from admin.routers import chat

    calls = []

    async def fake_owner_turn(message, provenance_channel, **kwargs):
        calls.append((message, provenance_channel, kwargs))
        return {"reply": "收到"}

    monkeypatch.setattr(chat, "run_owner_chat_turn", fake_owner_turn)
    monkeypatch.setattr(chat, "_check_reality_not_in_dream", lambda uid: None)
    monkeypatch.setattr(
        "core.config_loader.get_config",
        lambda: {"scheduler": {"owner_id": "owner"}},
    )
    monkeypatch.setattr("core.scheduler.sensor_events.notify_chat_happened", lambda: None)

    await chat.desktop_chat({"message": "你好"}, _auth=True)

    assert calls == [("你好", "desktop", {"reply_to": None})]


def test_mobile_probe_prompt_excludes_desktop_tools(monkeypatch):
    from core import tool_dispatcher

    monkeypatch.setattr(tool_dispatcher, "get_active_char_name", lambda: "Companion")
    prompt = tool_dispatcher.get_probe_prompt("测试位置", categories=["info"])

    desktop_tools = [
        name
        for name, spec in tool_dispatcher._TOOL_REGISTRY.items()
        if spec.get("category") in {"desktop", "system", "phone_control"}
    ]
    assert desktop_tools
    assert all(name not in prompt for name in desktop_tools)


async def test_mobile_owner_turn_uses_mobile_context_without_desktop_stream(monkeypatch):
    from admin.routers import chat

    class _Character:
        name = "Companion"

    class _Pipeline:
        character = _Character()

        def _current_reality_scope(self, _uid):
            return SimpleNamespace(character_id="companion")

        async def fetch_context(self, *_args, **_kwargs):
            return {}

        def build_prompt(self, _uid, _message, _context, **kwargs):
            prompt_channels.append(kwargs["channel"])
            return [], {}

        async def run_llm(self, _messages):
            return "手机回复"

        async def run_llm_stream(self, _messages, **_kwargs):
            raise AssertionError("mobile provenance must not enable desktop stream")

    class _Channel:
        def __init__(self):
            self.active = False

        def set_active(self, value):
            self.active = value

    prompt_channels = []
    probe_channels = []
    capture_origins = []
    sink_calls = []
    mobile_channel = _Channel()
    desktop_channel = _Channel()

    async def fake_probe(_message, _uid, *, char_id, provenance_channel):
        assert char_id == "companion"
        probe_channels.append(provenance_channel)
        return None

    async def fake_sink(**kwargs):
        sink_calls.append(kwargs)
        return SimpleNamespace(
            turn_id="turn-mobile",
            written_to_memory=True,
            emotion="neutral",
        )

    monkeypatch.setattr("core.pipeline_registry.get", lambda: _Pipeline())
    monkeypatch.setattr(
        "core.config_loader.get_config",
        lambda: {"scheduler": {"owner_id": "owner"}},
    )
    monkeypatch.setattr("core.scheduler.loop.mark_user_active", lambda: None)
    monkeypatch.setattr("core.scheduler.state_machine.notify_owner_turn", lambda _uid: None)
    monkeypatch.setattr("core.tool_dispatcher.tool_loop_active", lambda _uid: False)
    monkeypatch.setattr(chat, "_probe_and_execute_tools", fake_probe)
    monkeypatch.setattr(
        "core.observe.prompt_capture.set_capture_origin",
        lambda origin: capture_origins.append(origin),
    )
    monkeypatch.setattr("channels.ui_push.any_connected", lambda: True)
    monkeypatch.setattr(
        "channels.registry.get",
        lambda name: {"mobile": mobile_channel, "desktop": desktop_channel}.get(name),
    )
    monkeypatch.setattr("core.turn_sink.record_assistant_turn", fake_sink)
    monkeypatch.setattr("core.coplay.session.is_active", lambda *_args, **_kwargs: False)
    result = await chat.run_owner_chat_turn(
        "你好",
        "mobile",
        live_origin_channel="mobile",
        durable_mobile_mirror=True,
    )

    assert result["turn_id"] == result["msg_id"] == "turn-mobile"
    assert "affection" not in result
    assert "level" not in result
    assert prompt_channels == ["mobile"]
    assert probe_channels == ["mobile"]
    assert len(capture_origins) == 1
    assert capture_origins[0]["origin"] == "mobile"
    assert capture_origins[0]["user_authored"] is True
    assert mobile_channel.active is True
    assert desktop_channel.active is False
    assert sink_calls[0]["exclude_origin_channel"] == "mobile"
    assert sink_calls[0]["durable_mobile_mirror"] is True


async def test_mobile_chat_dream_guard_blocks_before_owner_turn(sandbox, monkeypatch):
    from core.dream.dream_state import DreamStatus
    from fastapi import HTTPException

    from core.dream.dream_state import write_state
    write_state("owner", {"status": DreamStatus.DREAM_ACTIVE.value, "user_id": "owner"})
    monkeypatch.setattr(
        "core.config_loader.get_config",
        lambda: {"scheduler": {"owner_id": "owner"}},
    )

    from admin.routers import mobile

    with pytest.raises(HTTPException) as exc:
        await mobile.mobile_chat({"message": "你好"}, _auth=True)
    assert exc.value.status_code == 409


async def test_mobile_chat_reaches_turn_sink_with_pipeline_critical_contract(monkeypatch):
    """Exercise mobile -> owner chat -> turn sink without mocking either boundary."""
    from admin.routers import chat, mobile
    from core.memory.scope import MemoryScope
    from core.pipeline import Pipeline

    critical_calls = []

    class _Character:
        name = "Companion"

    class _Pipeline:
        character = _Character()
        _active_character_id = "companion"

        def _current_reality_scope(self, uid):
            return MemoryScope.reality_scope(uid, "companion")

        async def fetch_context(self, *_args, **_kwargs):
            return {}

        def build_prompt(self, *_args, **_kwargs):
            return [], {}

        async def run_llm(self, _messages):
            return "mobile reply"

        async def post_process_critical(self, uid, content, reply, **kwargs):
            # Bind against the production method instead of accepting arbitrary
            # kwargs silently. This catches turn_sink/Pipeline signature drift.
            inspect.signature(Pipeline.post_process_critical).bind(
                None, uid, content, reply, **kwargs
            )
            critical_calls.append(kwargs)
            return {
                "turn_id": "turn-mobile-real-chain",
                "critical_written": True,
                "emotion": "neutral",
                "char_id": "companion",
                "scope_payload": {},
                "should_update_profile": False,
                "profile_recent": [],
            }

        async def post_process_slow(self, *_args, **_kwargs):
            return {"emotion": "neutral", "turn_id": "turn-mobile-real-chain"}

    async def fake_probe(*_args, **_kwargs):
        return None

    monkeypatch.setattr("core.pipeline_registry.get", lambda: _Pipeline())
    monkeypatch.setattr(
        "core.config_loader.get_config",
        lambda: {"scheduler": {"owner_id": "owner"}},
    )
    monkeypatch.setattr(chat, "_check_reality_not_in_dream", lambda _uid: None)
    monkeypatch.setattr("core.scheduler.loop.mark_user_active", lambda: None)
    monkeypatch.setattr("core.scheduler.state_machine.notify_owner_turn", lambda _uid: None)
    monkeypatch.setattr("core.scheduler.proactive_ledger.record_user_message", lambda _uid: None)
    monkeypatch.setattr("core.scheduler.sensor_events.notify_chat_happened", lambda: None)
    monkeypatch.setattr("core.tool_dispatcher.tool_loop_active", lambda _uid: False)
    monkeypatch.setattr(chat, "_probe_and_execute_tools", fake_probe)
    monkeypatch.setattr("core.coplay.session.is_active", lambda *_args, **_kwargs: False)
    monkeypatch.setattr("channels.registry._channels", {})

    result = await mobile.mobile_chat({"message": "hello"}, _auth=True)

    assert result["turn_id"] == result["msg_id"] == "turn-mobile-real-chain"
    assert len(critical_calls) == 1
    assert critical_calls[0]["provenance_source"] == ""
    assert critical_calls[0]["event_channel"] == "mobile"
