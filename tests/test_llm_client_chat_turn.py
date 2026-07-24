"""
tests/test_llm_client_chat_turn.py — chat_turn() 对"泄漏的模型内部工具调用 token"的防御

背景（cc-tasks/122）：DeepSeek 等模型的原生工具调用格式用带内部 special token
（如 `<｜tool▁calls▁begin｜>`）的文本包裹；正常情况下网关应该把这段解析成结构化
的 `tool_calls` 字段，`content` 里不该出现这些 token。观察到的真实故障：网关这一步
没解析干净，`finish_reason` 没标 `tool_calls`，`message.content` 却混进了这类内部
token，原样展示给用户就是一堆乱码指令。

`chat_turn()` 现在探测到这种情况会丢弃 content、按空内容处理，复用
run_agentic_loop 里已有的"空回复→不带 tools 强制重新生成"兜底。
"""

from __future__ import annotations

import types

import pytest

from core.model_registry import ModelClient


def _fake_message(content: str, *, tool_calls=None, model_dump_extra: dict | None = None):
    dump = {"role": "assistant"}
    if content:
        dump["content"] = content
    if model_dump_extra:
        dump.update(model_dump_extra)

    return types.SimpleNamespace(
        content=content,
        tool_calls=tool_calls,
        model_dump=lambda exclude_none=True: dict(dump),
    )


def _make_fake_model_client(message, *, finish_reason="stop"):
    async def fake_create(**kwargs):
        choice = types.SimpleNamespace(message=message, finish_reason=finish_reason)
        return types.SimpleNamespace(choices=[choice])

    completions = types.SimpleNamespace(create=fake_create)
    chat_obj = types.SimpleNamespace(completions=completions)
    fake_client = types.SimpleNamespace(chat=chat_obj)

    return ModelClient(
        name="test",
        provider_kind="deepseek",
        model="test-model",
        tool_call_mode="function_calling",
        prompt_style="narrative",
        params={"temperature": 0.0, "max_tokens": 10},
        client=fake_client,
    )


@pytest.mark.asyncio
async def test_leaked_tool_call_markup_discarded_as_empty(monkeypatch):
    from core import llm_client

    leaked = "<｜｜DSML｜｜tool_calls>疑似残留的内部调用指令"
    message = _fake_message(leaked, tool_calls=None)
    fake_mc = _make_fake_model_client(message, finish_reason="stop")
    monkeypatch.setattr(llm_client, "get_model_client", lambda cat, char_id=None: fake_mc)

    turn = await llm_client.chat_turn(
        [{"role": "user", "content": "去调用工具玩一下"}], tools=[{"type": "function", "function": {"name": "x", "parameters": {}}}],
    )

    assert turn.content == ""
    assert turn.tool_calls == []
    assert turn.assistant_message.get("content") is None


@pytest.mark.asyncio
async def test_clean_natural_content_passes_through_unchanged(monkeypatch):
    """回归：不含泄漏特征字符的正常回复不受影响。"""
    from core import llm_client

    message = _fake_message("今天天气不错，我们出去走走吧", tool_calls=None)
    fake_mc = _make_fake_model_client(message, finish_reason="stop")
    monkeypatch.setattr(llm_client, "get_model_client", lambda cat, char_id=None: fake_mc)

    turn = await llm_client.chat_turn(
        [{"role": "user", "content": "hi"}], tools=[{"type": "function", "function": {"name": "x", "parameters": {}}}],
    )

    assert turn.content == "今天天气不错，我们出去走走吧"
    assert turn.tool_calls == []


@pytest.mark.asyncio
async def test_real_tool_calls_bypass_leak_check_even_with_suspicious_content(monkeypatch):
    """回归：finish_reason 真是 tool_calls 时，即使 content 恰好也带这些字符
    （现实中不会发生，但确认判断逻辑只在 not tool_calls 时才生效），照常解析。"""
    from core import llm_client

    tc = types.SimpleNamespace(
        id="call_1",
        function=types.SimpleNamespace(name="web_search", arguments='{"query": "x"}'),
    )
    message = _fake_message("｜无关噪音｜", tool_calls=[tc])
    fake_mc = _make_fake_model_client(message, finish_reason="tool_calls")
    monkeypatch.setattr(llm_client, "get_model_client", lambda cat, char_id=None: fake_mc)

    turn = await llm_client.chat_turn(
        [{"role": "user", "content": "hi"}], tools=[{"type": "function", "function": {"name": "web_search", "parameters": {}}}],
    )

    assert len(turn.tool_calls) == 1
    assert turn.tool_calls[0]["name"] == "web_search"
    assert turn.content == "｜无关噪音｜"


class TestLeakDetectorHelper:
    def test_two_or_more_occurrences_flagged(self):
        from core.llm_client import _looks_like_leaked_tool_call_markup as detect

        assert detect("<｜tool▁calls▁begin｜>") is True
        assert detect("<｜｜DSML｜｜tool_calls>") is True

    def test_single_occurrence_not_flagged(self):
        from core.llm_client import _looks_like_leaked_tool_call_markup as detect

        assert detect("只有一个｜竖线的正常句子") is False

    def test_empty_or_none_not_flagged(self):
        from core.llm_client import _looks_like_leaked_tool_call_markup as detect

        assert detect("") is False
        assert detect(None) is False
