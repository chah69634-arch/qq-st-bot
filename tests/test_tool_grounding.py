from __future__ import annotations

import time

import pytest


@pytest.mark.asyncio
async def test_required_intent_is_marked_even_when_tool_is_not_exposed(monkeypatch):
    from core import tool_dispatcher
    from core.pretool_router import route_pretool

    monkeypatch.setattr(tool_dispatcher, "get_tools_schema", lambda categories=None: [])
    monkeypatch.setattr("core.growth.mcp_proficiency.filter_schemas", lambda items, char_id: items)
    monkeypatch.setattr("core.self_management.policy.tool_allowed", lambda *args, **kwargs: True)
    monkeypatch.setitem(tool_dispatcher._TOOL_REGISTRY, "weather", {
        "keywords": ["天气"], "category": "info", "parameters": {"required": []},
    })

    class State:
        NORMAL = "normal"
        WAITING_CONFIRM = "waiting_confirm"
        WAITING_INPUT = "waiting_input"
        status = NORMAL

    result = await route_pretool(
        "查天气", "u-ground", "c1", "qq", "u-ground", False, State(),
        tool_loop_enabled=True, categories=["info"],
    )
    assert result.must_call_tool is True
    assert result.required_tool_names == {"weather"}
    assert result.route == "skipped_for_tool_loop"


def test_failed_required_call_replaces_completion_claim():
    from core.tool_grounding import GROUNDING_LAYER, guard_completion_claim

    messages = [{
        "role": "system",
        "_layer": GROUNDING_LAYER,
        "_tool_grounding": {
            "required": True, "tool_names": ["weather"], "result_validity": "execution_failed",
        },
    }]
    guarded = guard_completion_claim("已经查到北京天气了。", messages)
    assert "已经查到" not in guarded
    assert "没有拿到可确认的成功结果" in guarded


def test_successful_current_tool_result_allows_claim():
    from core.tool_grounding import GROUNDING_LAYER, guard_completion_claim

    messages = [{
        "role": "system",
        "_layer": GROUNDING_LAYER,
        "_tool_grounding": {
            "required": True, "tool_names": ["weather"], "result_validity": "current_turn",
        },
    }]
    assert guard_completion_claim("已经查到北京天气了。", messages) == "已经查到北京天气了。"


def test_history_trace_is_not_current_result():
    from core.memory.action_trace import format_trace_block

    block = format_trace_block([{
        "ts": time.time() - 3600,
        "tool": "weather",
        "status": "ok",
        "result_digest": "北京多云",
    }])
    assert "历史操作参考" in block
    assert "不是本轮工具结果" in block


def test_tool_result_frame_carries_time_and_failure_validity():
    from core.tools.tool_result import frame_tool_result

    framed = frame_tool_result(
        "服务不可用",
        char_name="Companion",
        generated_at=0,
        validity="execution_failed",
    )
    assert "1970-01-01" in framed
    assert "本轮执行失败" in framed
    assert "不得当作已完成事实" in framed
