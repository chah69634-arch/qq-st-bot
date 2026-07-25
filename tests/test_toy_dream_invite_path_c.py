"""
tests/test_toy_dream_invite_path_c.py

Brief 103/109 收尾：toy_invite / dream_invite 此前只经 Path B
(_parse_and_execute_intent) 触发，从未注册进 _TOOL_REGISTRY。Path B 已被
config.intent_reflex.enabled=false 关闭且计划到期整删（cc-tasks/103），
若不迁移这两个动作会在删除后无任何路径可触发。

本测试验证迁移落地：
- 两个工具已注册进 _TOOL_REGISTRY，category=desktop，无必填参数。
- 调用 wrapper 时推送的 action payload 与 Path B 原始行为完全一致
  （type="toy_invite"/"dream_invite"，无额外 params），保证桌面客户端侧
  协议不变（前端不用改）。
- execute() 走 desktop 分类的安全模式闸门（_MODE_RESTRICTED_CATEGORIES）。
"""

import pytest
from unittest.mock import AsyncMock, patch


class TestRegistration:
    def test_toy_invite_registered(self):
        from core.tool_dispatcher import _TOOL_REGISTRY
        assert "toy_invite" in _TOOL_REGISTRY
        spec = _TOOL_REGISTRY["toy_invite"]
        assert spec["category"] == "desktop"
        assert spec["dangerous"] is False
        assert spec["parameters"]["required"] == []
        assert spec.get("examples")
        assert spec.get("keywords")

    def test_dream_invite_registered(self):
        from core.tool_dispatcher import _TOOL_REGISTRY
        assert "dream_invite" in _TOOL_REGISTRY
        spec = _TOOL_REGISTRY["dream_invite"]
        assert spec["category"] == "desktop"
        assert spec["dangerous"] is False
        assert spec["parameters"]["required"] == []
        assert spec.get("examples")
        assert spec.get("keywords")


class TestPushPayloadMatchesPathB:
    @pytest.mark.asyncio
    async def test_toy_invite_wrapper_payload(self):
        from core.tool_dispatcher import _toy_invite_wrapper
        with patch(
            "core.tool_dispatcher._push_desktop_action",
            new=AsyncMock(return_value="ok"),
        ) as mock_push:
            result = await _toy_invite_wrapper()
        mock_push.assert_awaited_once_with({"type": "toy_invite"})
        assert result != "ok"  # 应转成人话反馈，不是原样透传状态字符串

    @pytest.mark.asyncio
    async def test_dream_invite_wrapper_payload(self):
        from core.tool_dispatcher import _dream_invite_wrapper
        with patch(
            "core.tool_dispatcher._push_desktop_action",
            new=AsyncMock(return_value="ok"),
        ) as mock_push:
            result = await _dream_invite_wrapper()
        mock_push.assert_awaited_once_with({"type": "dream_invite"})
        assert result != "ok"

    @pytest.mark.asyncio
    async def test_toy_invite_wrapper_propagates_failure(self):
        from core.tool_dispatcher import _toy_invite_wrapper
        with patch(
            "core.tool_dispatcher._push_desktop_action",
            new=AsyncMock(return_value="端离线，动作未执行"),
        ):
            result = await _toy_invite_wrapper()
        assert result == "端离线，动作未执行"


class TestDesktopModeGate:
    @pytest.mark.asyncio
    async def test_toy_invite_blocked_in_safe_mode(self, monkeypatch):
        """desktop 分类工具在 execute() 层受 _MODE_RESTRICTED_CATEGORIES 闸门约束，
        安全模式下不得真的推送桌面动作。"""
        from core import tool_dispatcher as td

        monkeypatch.setattr(td, "_current_mode", lambda: "safe")
        with patch(
            "core.tool_dispatcher._push_desktop_action",
            new=AsyncMock(return_value="ok"),
        ) as mock_push:
            result, _ = await td.execute(
                "toy_invite", {}, user_id="owner", target_id="owner",
                is_group=False, session_state={}, origin="user_live",
                char_id="test_char",
            )
        mock_push.assert_not_awaited()
        assert "安全模式" in (result or "")
