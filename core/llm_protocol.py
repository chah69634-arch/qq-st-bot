"""Protocol boundary for OpenAI Chat Completions and Responses API calls.

The rest of PresenceKit consumes normalized assistant text and tool calls.  This
module is the only place that knows either wire format.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, AsyncIterator


VALID_API_PROTOCOLS = frozenset({"chat_completions", "responses"})


class UpstreamResponseFormatError(RuntimeError):
    """The gateway response does not match the preset's declared protocol."""


def _protocol(mc: Any) -> str:
    """Keep older test doubles and external callers on the legacy default."""
    value = getattr(mc, "api_protocol", "chat_completions")
    return value if isinstance(value, str) else "chat_completions"


@dataclass
class NormalizedToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class NormalizedResponse:
    assistant_text: str
    tool_calls: list[NormalizedToolCall]
    status: str
    usage: dict[str, Any] | None
    continuation_items: list[dict[str, Any]]
    raw_response: Any


def _diagnostic(mc: Any, response: Any = None) -> str:
    status = getattr(response, "status_code", None)
    suffix = f" http_status={status}" if status is not None else ""
    return (
        f"preset={mc.name!r} provider={mc.provider_kind!r} model={mc.model!r} "
        f"api_protocol={_protocol(mc)!r} response_type={type(response).__name__}{suffix}"
    )


def _format_error(mc: Any, message: str, response: Any = None) -> UpstreamResponseFormatError:
    return UpstreamResponseFormatError(f"{message}; {_diagnostic(mc, response)}")


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        return dump(exclude_none=True)
    if hasattr(value, "__dict__"):
        return dict(vars(value))
    return {}


def _parse_arguments(mc: Any, value: Any, response: Any = None) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if not isinstance(value, str):
        raise _format_error(mc, "tool call arguments are not a JSON string", response)
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise _format_error(mc, "tool call arguments are invalid JSON", response) from exc
    if not isinstance(parsed, dict):
        raise _format_error(mc, "tool call arguments must decode to an object", response)
    return parsed


def _usage(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    result = _as_dict(value)
    return result or None


def _chat_assistant_message(message: Any) -> dict[str, Any]:
    dump = getattr(message, "model_dump", None)
    if callable(dump):
        return dump(exclude_none=True)
    result: dict[str, Any] = {"role": "assistant"}
    content = getattr(message, "content", None)
    if content is not None:
        result["content"] = content
    calls = getattr(message, "tool_calls", None)
    if calls:
        result["tool_calls"] = [
            {
                "id": getattr(call, "id", ""),
                "type": "function",
                "function": {
                    "name": getattr(getattr(call, "function", None), "name", ""),
                    "arguments": getattr(getattr(call, "function", None), "arguments", "{}"),
                },
            }
            for call in calls
        ]
    return result


def _normalize_chat_completion(mc: Any, response: Any) -> NormalizedResponse:
    choices = getattr(response, "choices", None)
    if not isinstance(choices, list) or not choices:
        raise _format_error(mc, "expected an OpenAI ChatCompletion with choices[0].message", response)
    choice = choices[0]
    message = getattr(choice, "message", None)
    if message is None or not hasattr(message, "content"):
        raise _format_error(mc, "ChatCompletion response is missing choices[0].message.content", response)

    tool_calls: list[NormalizedToolCall] = []
    if getattr(choice, "finish_reason", None) == "tool_calls" and getattr(message, "tool_calls", None):
        for call in message.tool_calls:
            function = getattr(call, "function", None)
            call_id = getattr(call, "id", None)
            name = getattr(function, "name", None)
            if not isinstance(call_id, str) or not call_id or not isinstance(name, str) or not name:
                raise _format_error(mc, "ChatCompletion tool call is missing id or name", response)
            tool_calls.append(
                NormalizedToolCall(
                    id=call_id,
                    name=name,
                    arguments=_parse_arguments(mc, getattr(function, "arguments", None), response),
                )
            )
    return NormalizedResponse(
        assistant_text=getattr(message, "content", None) or "",
        tool_calls=tool_calls,
        status=str(getattr(choice, "finish_reason", "") or ""),
        usage=_usage(getattr(response, "usage", None)),
        continuation_items=[_chat_assistant_message(message)],
        raw_response=response,
    )


def _message_text(content: Any) -> str:
    if not isinstance(content, str):
        raise ValueError("Responses input only supports string message content in this adapter")
    return content


def responses_input(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert the existing structured conversation without flattening its order."""
    result: list[dict[str, Any]] = []
    for message in messages:
        item_type = message.get("type")
        if item_type == "function_call":
            call_id = message.get("call_id")
            name = message.get("name")
            arguments = message.get("arguments")
            if not all(isinstance(value, str) and value for value in (call_id, name, arguments)):
                raise ValueError("Responses function-call history is missing call_id, name, or arguments")
            result.append({
                "type": "function_call", "call_id": call_id, "name": name, "arguments": arguments,
            })
            continue
        if item_type == "function_call_output":
            call_id = message.get("call_id")
            output = message.get("output")
            if not isinstance(call_id, str) or not call_id or not isinstance(output, str):
                raise ValueError("Responses function-call output history is invalid")
            result.append({"type": "function_call_output", "call_id": call_id, "output": output})
            continue
        if item_type == "message" and message.get("role") == "assistant":
            content = message.get("content")
            if not isinstance(content, list):
                raise ValueError("Responses assistant message history has invalid content")
            result.append({"type": "message", "role": "assistant", "content": list(content)})
            continue
        role = message.get("role")
        content = message.get("content")
        if role in {"system", "developer", "user"}:
            result.append({
                "type": "message",
                "role": role,
                "content": [{"type": "input_text", "text": _message_text(content)}],
            })
        elif role == "assistant":
            if content:
                result.append({
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": _message_text(content)}],
                })
            for call in message.get("tool_calls") or []:
                function = call.get("function") or {}
                call_id = call.get("id")
                name = function.get("name")
                arguments = function.get("arguments")
                if not all(isinstance(value, str) and value for value in (call_id, name, arguments)):
                    raise ValueError("assistant tool history is missing id, name, or JSON arguments")
                result.append({
                    "type": "function_call",
                    "call_id": call_id,
                    "name": name,
                    "arguments": arguments,
                })
        elif role == "tool":
            call_id = message.get("tool_call_id")
            if not isinstance(call_id, str) or not call_id:
                raise ValueError("tool history is missing tool_call_id")
            result.append({
                "type": "function_call_output",
                "call_id": call_id,
                "output": _message_text(content),
            })
        else:
            raise ValueError(f"unsupported message role for Responses API: {role!r}")
    return result


def responses_tools(tools: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
    if not tools:
        return None
    result: list[dict[str, Any]] = []
    for tool in tools:
        function = tool.get("function", tool)
        name = function.get("name")
        parameters = function.get("parameters")
        if not isinstance(name, str) or not name or not isinstance(parameters, dict):
            raise ValueError("invalid function tool schema")
        item: dict[str, Any] = {"type": "function", "name": name, "parameters": parameters}
        if "description" in function:
            item["description"] = function["description"]
        if "strict" in function:
            item["strict"] = function["strict"]
        result.append(item)
    return result


def _responses_kwargs(gen_kwargs: dict[str, Any]) -> dict[str, Any]:
    result = dict(gen_kwargs)
    if "max_tokens" in result:
        result["max_output_tokens"] = result.pop("max_tokens")
    # These parameters are accepted by Chat Completions but not by Responses.
    result.pop("frequency_penalty", None)
    result.pop("presence_penalty", None)
    return result


def _normalize_responses(mc: Any, response: Any) -> NormalizedResponse:
    output = getattr(response, "output", None)
    status = getattr(response, "status", None)
    if status != "completed":
        if status == "incomplete":
            raise _format_error(mc, "Responses API returned an incomplete response", response)
        if status == "failed":
            raise _format_error(mc, "Responses API returned a failed response", response)
        raise _format_error(mc, "Responses API response is missing completed status", response)
    if not isinstance(output, list) or not output:
        raise _format_error(mc, "Responses API output has no consumable items", response)

    text_parts: list[str] = []
    tool_calls: list[NormalizedToolCall] = []
    continuation_items: list[dict[str, Any]] = []
    saw_consumable = False
    for item in output:
        item_type = getattr(item, "type", None)
        if item_type == "message":
            content = getattr(item, "content", None)
            if not isinstance(content, list):
                raise _format_error(mc, "Responses message output has invalid content", response)
            output_text_parts: list[str] = []
            for part in content:
                if getattr(part, "type", None) != "output_text":
                    raise _format_error(mc, "Responses message output has an unknown content item", response)
                text = getattr(part, "text", None)
                if not isinstance(text, str):
                    raise _format_error(mc, "Responses output_text is not text", response)
                text_parts.append(text)
                output_text_parts.append(text)
            if output_text_parts:
                continuation_items.append({
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": text} for text in output_text_parts],
                })
                saw_consumable = True
        elif item_type == "function_call":
            call_id = getattr(item, "call_id", None)
            name = getattr(item, "name", None)
            if not isinstance(call_id, str) or not call_id or not isinstance(name, str) or not name:
                raise _format_error(mc, "Responses function call is missing call_id or name", response)
            arguments_raw = getattr(item, "arguments", None)
            tool_calls.append(NormalizedToolCall(
                id=call_id,
                name=name,
                arguments=_parse_arguments(mc, arguments_raw, response),
            ))
            continuation_items.append({
                "type": "function_call",
                "call_id": call_id,
                "name": name,
                "arguments": arguments_raw,
            })
            saw_consumable = True
        elif item_type == "reasoning":
            # Reasoning is neither rendered nor persisted. The current loop has no
            # stateful previous_response_id contract, so it is deliberately absent
            # from continuation input as well.
            continue
        else:
            raise _format_error(mc, f"Responses API output contains unknown item type {item_type!r}", response)
    if not saw_consumable:
        raise _format_error(mc, "Responses API output has no assistant text or function call", response)
    return NormalizedResponse(
        assistant_text="".join(text_parts),
        tool_calls=tool_calls,
        status=status,
        usage=_usage(getattr(response, "usage", None)),
        continuation_items=continuation_items,
        raw_response=response,
    )


async def create(
    mc: Any,
    messages: list[dict[str, Any]],
    *,
    tools: list[dict[str, Any]] | None,
    tool_choice: str | None,
    gen_kwargs: dict[str, Any],
) -> NormalizedResponse:
    """Call the declared wire protocol and normalize its response."""
    protocol = _protocol(mc)
    if protocol == "chat_completions":
        kwargs = dict(gen_kwargs)
        if tools:
            kwargs.update(tools=tools, tool_choice=tool_choice or "auto")
        response = await mc.client.chat.completions.create(model=mc.model, messages=messages, **kwargs)
        return _normalize_chat_completion(mc, response)
    if protocol != "responses":
        raise _format_error(mc, "unknown api_protocol")
    responses = getattr(mc.client, "responses", None)
    if responses is None or not callable(getattr(responses, "create", None)):
        raise _format_error(mc, "installed OpenAI SDK does not support client.responses.create")
    kwargs = _responses_kwargs(gen_kwargs)
    kwargs.update(
        input=responses_input(messages),
        store=False,
    )
    converted_tools = responses_tools(tools)
    if converted_tools:
        kwargs["tools"] = converted_tools
        kwargs["tool_choice"] = tool_choice or "auto"
    response = await responses.create(model=mc.model, **kwargs)
    return _normalize_responses(mc, response)


async def stream_text(
    mc: Any,
    messages: list[dict[str, Any]],
    *,
    gen_kwargs: dict[str, Any],
) -> AsyncIterator[str]:
    """Yield text deltas while validating the declared protocol's stream state."""
    if _protocol(mc) == "chat_completions":
        stream = await mc.client.chat.completions.create(
            model=mc.model, messages=messages, stream=True, **gen_kwargs,
        )
        async for chunk in stream:
            choices = getattr(chunk, "choices", None)
            if not isinstance(choices, list) or not choices:
                continue
            delta = getattr(choices[0], "delta", None)
            text = getattr(delta, "content", None)
            if text:
                yield text
        return
    if _protocol(mc) != "responses":
        raise _format_error(mc, "unknown api_protocol")
    responses = getattr(mc.client, "responses", None)
    if responses is None or not callable(getattr(responses, "create", None)):
        raise _format_error(mc, "installed OpenAI SDK does not support client.responses.create")

    stream = await responses.create(
        model=mc.model,
        input=responses_input(messages),
        stream=True,
        store=False,
        **_responses_kwargs(gen_kwargs),
    )
    completed = False
    emitted = ""
    function_argument_deltas: dict[str, str] = {}
    async for event in stream:
        event_type = getattr(event, "type", None)
        if event_type == "response.output_text.delta":
            delta = getattr(event, "delta", None)
            if not isinstance(delta, str):
                raise _format_error(mc, "Responses text delta is not text", event)
            emitted += delta
            yield delta
        elif event_type == "response.function_call_arguments.delta":
            item_id = str(getattr(event, "item_id", ""))
            delta = getattr(event, "delta", None)
            if not isinstance(delta, str):
                raise _format_error(mc, "Responses function argument delta is not text", event)
            function_argument_deltas[item_id] = function_argument_deltas.get(item_id, "") + delta
        elif event_type in {"response.function_call_arguments.done", "response.output_item.done"}:
            # These events establish tool/item completion. The final completed
            # response below remains the authoritative normalized result.
            continue
        elif event_type == "response.completed":
            normalized = _normalize_responses(mc, getattr(event, "response", None))
            if normalized.tool_calls:
                raise _format_error(mc, "Responses text stream unexpectedly returned function calls", event)
            if normalized.assistant_text and not emitted:
                emitted = normalized.assistant_text
                yield normalized.assistant_text
            completed = True
        elif event_type in {"response.failed", "response.incomplete", "error"}:
            raise _format_error(mc, f"Responses stream terminated with {event_type}", event)
        # Other lifecycle events (created, queued, in_progress, content part) do
        # not carry user-visible text and are intentionally ignored.
    if not completed:
        raise _format_error(mc, "Responses stream ended before response.completed")
