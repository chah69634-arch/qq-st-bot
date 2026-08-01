"""Responses API adapter coverage using local fake SDK objects only."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from core.llm_protocol import UpstreamResponseFormatError, create, responses_input, stream_text
from core.model_registry import ModelClient


def _message(text: str):
    return SimpleNamespace(
        type="message",
        role="assistant",
        content=[SimpleNamespace(type="output_text", text=text)],
    )


def _function_call(call_id: str = "call_weather", arguments: str = '{"city":"Hangzhou"}'):
    return SimpleNamespace(type="function_call", call_id=call_id, name="get_weather", arguments=arguments)


def _response(*items, status="completed", usage=None):
    return SimpleNamespace(output=list(items), status=status, usage=usage)


def _client(*, response=None, stream_events=None):
    calls = []

    async def create_response(**kwargs):
        calls.append(kwargs)
        if stream_events is not None:
            async def stream():
                for event in stream_events:
                    yield event
            return stream()
        return response

    return SimpleNamespace(
        responses=SimpleNamespace(create=create_response),
        calls=calls,
    )


def _responses_mc(client):
    return ModelClient(
        name="responses-test",
        provider_kind="openai",
        model="test-model",
        tool_call_mode="function_calling",
        prompt_style="narrative",
        params={"temperature": 0.2, "max_tokens": 64, "presence_penalty": 1.0},
        client=client,
        api_protocol="responses",
    )


@pytest.mark.asyncio
async def test_responses_text_is_normalized_and_uses_responses_wire_shape():
    client = _client(response=_response(_message("hello"), usage=SimpleNamespace(input_tokens=3, output_tokens=2)))
    result = await create(
        _responses_mc(client),
        [{"role": "system", "content": "be concise"}, {"role": "user", "content": "hi"}],
        tools=None,
        tool_choice=None,
        gen_kwargs={"temperature": 0.2, "max_tokens": 64, "presence_penalty": 1.0, "timeout": 8},
    )

    assert result.assistant_text == "hello"
    assert result.tool_calls == []
    assert result.usage == {"input_tokens": 3, "output_tokens": 2}
    request = client.calls[0]
    assert request["store"] is False
    assert request["max_output_tokens"] == 64
    assert "max_tokens" not in request
    assert "presence_penalty" not in request
    assert request["input"][0]["role"] == "system"
    assert request["input"][1]["content"][0] == {"type": "input_text", "text": "hi"}


@pytest.mark.asyncio
async def test_responses_function_call_round_trips_same_call_id_into_tool_output():
    client = _client(response=_response(_function_call()))
    result = await create(
        _responses_mc(client),
        [{"role": "user", "content": "weather"}],
        tools=[{"type": "function", "function": {"name": "get_weather", "description": "weather", "parameters": {"type": "object"}}}],
        tool_choice="auto",
        gen_kwargs={},
    )

    assert [(call.id, call.name, call.arguments) for call in result.tool_calls] == [
        ("call_weather", "get_weather", {"city": "Hangzhou"}),
    ]
    assert client.calls[0]["tools"] == [{
        "type": "function", "name": "get_weather", "description": "weather", "parameters": {"type": "object"},
    }]
    continuation = responses_input(result.continuation_items + [{
        "role": "tool", "tool_call_id": "call_weather", "content": "sunny",
    }])
    assert continuation[-2] == {
        "type": "function_call", "call_id": "call_weather", "name": "get_weather", "arguments": '{"city":"Hangzhou"}',
    }
    assert continuation[-1] == {"type": "function_call_output", "call_id": "call_weather", "output": "sunny"}


@pytest.mark.asyncio
async def test_responses_stream_requires_completed_event_and_yields_text_deltas():
    final = _response(_message("hello"))
    events = [
        SimpleNamespace(type="response.created"),
        SimpleNamespace(type="response.output_text.delta", delta="hel"),
        SimpleNamespace(type="response.function_call_arguments.delta", item_id="ignored", delta="{"),
        SimpleNamespace(type="response.output_text.delta", delta="lo"),
        SimpleNamespace(type="response.output_item.done"),
        SimpleNamespace(type="response.completed", response=final),
    ]
    pieces = [piece async for piece in stream_text(
        _responses_mc(_client(stream_events=events)),
        [{"role": "user", "content": "hi"}],
        gen_kwargs={},
    )]
    assert "".join(pieces) == "hello"


@pytest.mark.asyncio
async def test_responses_rejects_chat_completion_shape_and_empty_or_unknown_output():
    mc = _responses_mc(_client(response=SimpleNamespace(choices=[])))
    with pytest.raises(UpstreamResponseFormatError, match="missing completed status"):
        await create(mc, [], tools=None, tool_choice=None, gen_kwargs={})

    mc.client.responses.create = _client(response=_response()).responses.create
    with pytest.raises(UpstreamResponseFormatError, match="no consumable items"):
        await create(mc, [], tools=None, tool_choice=None, gen_kwargs={})

    mc.client.responses.create = _client(response=_response(SimpleNamespace(type="mystery"))).responses.create
    with pytest.raises(UpstreamResponseFormatError, match="unknown item type"):
        await create(mc, [], tools=None, tool_choice=None, gen_kwargs={})


@pytest.mark.asyncio
async def test_chat_protocol_rejects_responses_shape_and_missing_sdk_capability_is_explicit():
    async def wrong_shape(**_kwargs):
        return _response(_message("wrong"))

    chat_mc = ModelClient(
        name="chat-test", provider_kind="openai", model="test", tool_call_mode="function_calling",
        prompt_style="narrative", params={}, client=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
            create=wrong_shape,
        ))),
    )
    with pytest.raises(UpstreamResponseFormatError, match="expected an OpenAI ChatCompletion"):
        await create(chat_mc, [], tools=None, tool_choice=None, gen_kwargs={})

    missing_sdk = _responses_mc(SimpleNamespace())
    with pytest.raises(UpstreamResponseFormatError, match="does not support client.responses.create"):
        await create(missing_sdk, [], tools=None, tool_choice=None, gen_kwargs={})


@pytest.mark.asyncio
async def test_chat_turn_consumes_responses_tool_call(monkeypatch):
    from core import llm_client

    client = _client(response=_response(_function_call("call_42", '{"query":"rain"}')))
    mc = _responses_mc(client)
    monkeypatch.setattr(llm_client, "get_model_client", lambda *_args, **_kwargs: mc)
    monkeypatch.setattr(llm_client, "_record_debug_request", lambda **_kwargs: None)
    monkeypatch.setattr(llm_client, "_record_api_call", lambda **_kwargs: None)

    turn = await llm_client.chat_turn(
        [{"role": "user", "content": "search"}],
        [{"type": "function", "function": {"name": "get_weather", "parameters": {"type": "object"}}}],
    )
    assert turn.tool_calls == [{"id": "call_42", "name": "get_weather", "arguments": {"query": "rain"}}]
    assert turn.continuation_items == [{
        "type": "function_call", "call_id": "call_42", "name": "get_weather", "arguments": '{"query":"rain"}',
    }]


@pytest.mark.asyncio
async def test_responses_tool_loop_second_step_receives_function_call_output(monkeypatch):
    from core import llm_client

    client = _client(response=None)
    responses = iter([
        _response(_function_call("call_9", '{"city":"Hangzhou"}')),
        _response(_message("The weather is clear.")),
    ])

    async def create_response(**kwargs):
        client.calls.append(kwargs)
        return next(responses)

    client.responses.create = create_response
    mc = _responses_mc(client)
    monkeypatch.setattr(llm_client, "get_model_client", lambda *_args, **_kwargs: mc)
    monkeypatch.setattr(llm_client, "_record_debug_request", lambda **_kwargs: None)
    monkeypatch.setattr(llm_client, "_record_api_call", lambda **_kwargs: None)
    tools = [{"type": "function", "function": {"name": "get_weather", "parameters": {"type": "object"}}}]

    first = await llm_client.chat_turn([{"role": "user", "content": "weather"}], tools)
    second = await llm_client.chat_turn(
        first.continuation_items + [{
            "role": "tool", "tool_call_id": "call_9", "content": "clear",
        }],
        tools,
    )

    assert second.content == "The weather is clear."
    second_input = client.calls[1]["input"]
    assert {"type": "function_call_output", "call_id": "call_9", "output": "clear"} in second_input
