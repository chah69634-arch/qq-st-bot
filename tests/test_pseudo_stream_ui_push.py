"""tests/test_pseudo_stream_ui_push.py — Brief 84 §1: pseudo_stream_push helper.

Covers channels/ui_push.pseudo_stream_push():
- block splitting reconstructs the original text exactly
- frame order (start → delta×N → end) with optional char_id/round_id
- fail-open: not connected / config disabled / text too short to split / exception
  mid-stream never raises and never blocks the canonical push path
- max_duration_ms cap scales the per-block interval down for long text
"""
from __future__ import annotations
from tests.fixtures.public_assets import TEST_THIRD_CHAR_ID

import asyncio

import pytest


def _connect_desktop(monkeypatch):
    from channels import desktop_ws

    monkeypatch.setattr(desktop_ws, "_current_ws", object())


def _disconnect_all(monkeypatch):
    from channels import desktop_ws, device_ws

    monkeypatch.setattr(desktop_ws, "_current_ws", None)
    monkeypatch.setattr(device_ws, "_current_ws", None)


def _fast_sleep(monkeypatch):
    """Collapse real delays so tests don't pay the (small) wall-clock cost."""
    from channels import ui_push

    async def _noop(_seconds):
        return None

    monkeypatch.setattr(ui_push.asyncio, "sleep", _noop)


# ── block splitting ─────────────────────────────────────────────────────────

def test_split_into_blocks_reconstructs_original_text():
    from channels.ui_push import _split_into_blocks

    text = "今天天气不错，我们去散步吧！\n你说好不好呢？嗯……我想想"
    blocks = _split_into_blocks(text, 2, 6)

    assert "".join(blocks) == text
    assert all(1 <= len(b) <= 6 for b in blocks)


def test_split_into_blocks_handles_text_without_punctuation():
    from channels.ui_push import _split_into_blocks

    text = "helloworldnopunctuationhere"
    blocks = _split_into_blocks(text, 2, 6)

    assert "".join(blocks) == text
    assert all(1 <= len(b) <= 6 for b in blocks)


def test_split_into_blocks_empty_text_returns_empty():
    from channels.ui_push import _split_into_blocks

    assert _split_into_blocks("", 2, 6) == []


# ── pseudo_stream_push: frame order + payload ───────────────────────────────

@pytest.mark.asyncio
async def test_pseudo_stream_push_sends_start_delta_end_in_order(monkeypatch):
    from channels import ui_push

    _connect_desktop(monkeypatch)
    _fast_sleep(monkeypatch)

    sent = []

    async def fake_send(payload):
        sent.append(payload)
        return True

    monkeypatch.setattr("channels.desktop_ws._send_json", fake_send)

    await ui_push.pseudo_stream_push(
        "今天天气不错，我们去散步吧！你说好不好呢？",
        msg_id="msg-1",
        char_id=TEST_THIRD_CHAR_ID,
        round_id="round-1",
    )

    assert sent, "expected at least one frame when connected with splittable text"
    assert sent[0]["type"] == "message_stream_start"
    assert sent[0]["char_id"] == TEST_THIRD_CHAR_ID
    assert sent[0]["round_id"] == "round-1"
    assert sent[-1]["type"] == "message_stream_end"
    deltas = [f for f in sent[1:-1] if f["type"] == "message_stream_delta"]
    assert deltas, "expected at least one delta frame between start and end"
    assert all(f["msg_id"] == "msg-1" for f in sent)
    # Reassembling all deltas must reproduce the original text exactly.
    assert "".join(f["delta"] for f in deltas) == "今天天气不错，我们去散步吧！你说好不好呢？"


@pytest.mark.asyncio
async def test_pseudo_stream_push_omits_char_id_round_id_when_unspecified(monkeypatch):
    from channels import ui_push

    _connect_desktop(monkeypatch)
    _fast_sleep(monkeypatch)

    sent = []

    async def fake_send(payload):
        sent.append(payload)
        return True

    monkeypatch.setattr("channels.desktop_ws._send_json", fake_send)

    await ui_push.pseudo_stream_push(
        "这是一段没有指定角色和回合的文本，用来测试默认行为。", msg_id="msg-2",
    )

    start = sent[0]
    assert "char_id" not in start
    assert "round_id" not in start


# ── fail-open branches ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_pseudo_stream_push_noop_when_nothing_connected(monkeypatch):
    from channels import ui_push

    _disconnect_all(monkeypatch)

    called = []
    monkeypatch.setattr(
        "channels.desktop_ws._send_json",
        lambda payload: called.append(payload) or asyncio.sleep(0),
    )

    await ui_push.pseudo_stream_push("完全没有连接的情况下不应该发任何帧。", msg_id="msg-3")

    assert called == []


@pytest.mark.asyncio
async def test_pseudo_stream_push_noop_when_disabled_by_config(monkeypatch):
    from channels import ui_push

    _connect_desktop(monkeypatch)
    monkeypatch.setattr(
        "core.config_loader.get_config", lambda: {"pseudo_stream": {"enabled": False}}
    )

    sent = []

    async def fake_send(payload):
        sent.append(payload)
        return True

    monkeypatch.setattr("channels.desktop_ws._send_json", fake_send)

    await ui_push.pseudo_stream_push("配置关闭时不应该发任何流式帧。", msg_id="msg-4")

    assert sent == []


@pytest.mark.asyncio
async def test_pseudo_stream_push_noop_for_text_too_short_to_split(monkeypatch):
    from channels import ui_push

    _connect_desktop(monkeypatch)

    sent = []

    async def fake_send(payload):
        sent.append(payload)
        return True

    monkeypatch.setattr("channels.desktop_ws._send_json", fake_send)

    await ui_push.pseudo_stream_push("嗯", msg_id="msg-5")

    assert sent == []


@pytest.mark.asyncio
async def test_pseudo_stream_push_empty_text_or_missing_msg_id_is_noop(monkeypatch):
    from channels import ui_push

    _connect_desktop(monkeypatch)
    sent = []

    async def fake_send(payload):
        sent.append(payload)
        return True

    monkeypatch.setattr("channels.desktop_ws._send_json", fake_send)

    await ui_push.pseudo_stream_push("", msg_id="msg-6")
    await ui_push.pseudo_stream_push("有内容但没有 msg_id", msg_id="")

    assert sent == []


@pytest.mark.asyncio
async def test_pseudo_stream_push_exception_mid_stream_still_sends_end_and_never_raises(
    monkeypatch,
):
    from channels import ui_push

    _connect_desktop(monkeypatch)
    _fast_sleep(monkeypatch)

    sent = []

    async def flaky_delta(msg_id, delta):
        if len(sent) == 1:  # first delta after start
            raise RuntimeError("simulated WS failure")
        sent.append({"type": "message_stream_delta", "msg_id": msg_id, "delta": delta})

    async def fake_start(msg_id, **kw):
        sent.append({"type": "message_stream_start", "msg_id": msg_id, **kw})

    async def fake_end(msg_id):
        sent.append({"type": "message_stream_end", "msg_id": msg_id})

    monkeypatch.setattr(ui_push, "push_stream_start", fake_start)
    monkeypatch.setattr(ui_push, "push_stream_delta", flaky_delta)
    monkeypatch.setattr(ui_push, "push_stream_end", fake_end)

    # Must not raise — fail-open is the whole point of this helper.
    await ui_push.pseudo_stream_push(
        "第一句失败也不能影响后续。第二句还在。", msg_id="msg-7"
    )

    assert sent[0]["type"] == "message_stream_start"
    assert sent[-1]["type"] == "message_stream_end"


# ── config: profile merge + duration cap ────────────────────────────────────

def test_pseudo_stream_settings_merges_profile_override(monkeypatch):
    from channels import ui_push

    monkeypatch.setattr(
        "core.config_loader.get_config",
        lambda: {
            "pseudo_stream": {
                "interval_min_ms": 30,
                "interval_max_ms": 80,
                "profiles": {"dream": {"interval_min_ms": 50, "interval_max_ms": 120}},
            }
        },
    )

    default_settings = ui_push._pseudo_stream_settings("default")
    dream_settings = ui_push._pseudo_stream_settings("dream")

    assert default_settings["interval_min_ms"] == 30
    assert dream_settings["interval_min_ms"] == 50
    assert dream_settings["interval_max_ms"] == 120
    # profile override must not leak into unrelated keys' defaults
    assert dream_settings["max_duration_ms"] == ui_push._PSEUDO_STREAM_DEFAULTS["max_duration_ms"]


def test_pseudo_stream_settings_fail_open_on_config_error(monkeypatch):
    from channels import ui_push

    def _boom():
        raise RuntimeError("config load failed")

    monkeypatch.setattr("core.config_loader.get_config", _boom)

    settings = ui_push._pseudo_stream_settings("default")

    assert settings == ui_push._PSEUDO_STREAM_DEFAULTS


@pytest.mark.asyncio
async def test_pseudo_stream_push_long_text_caps_total_duration(monkeypatch):
    """超长文本自动加速，总回放时长不应远超 max_duration_ms 上限。"""
    from channels import ui_push
    import time

    _connect_desktop(monkeypatch)

    async def fake_send(payload):
        return True

    monkeypatch.setattr("channels.desktop_ws._send_json", fake_send)
    monkeypatch.setattr(
        "core.config_loader.get_config",
        lambda: {"pseudo_stream": {"max_duration_ms": 200}},
    )

    long_text = "很长很长的一段话。" * 40  # forces many blocks

    start = time.monotonic()
    await ui_push.pseudo_stream_push(long_text, msg_id="msg-8")
    elapsed = time.monotonic() - start

    # Generous margin over the 200ms cap to absorb scheduling jitter.
    assert elapsed < 1.5
