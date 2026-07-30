"""Contract tests for the separate mobile reality-chat endpoint."""

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
    monkeypatch.setattr(
        "core.memory.user_profile.get_affection_level",
        lambda _uid: {"value": 0, "label": "normal"},
    )

    result = await chat.run_owner_chat_turn(
        "你好",
        "mobile",
        live_origin_channel="mobile",
        durable_mobile_mirror=True,
    )

    assert result["turn_id"] == result["msg_id"] == "turn-mobile"
    assert prompt_channels == ["mobile"]
    assert probe_channels == ["mobile"]
    assert capture_origins == [{"origin": "mobile"}]
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
