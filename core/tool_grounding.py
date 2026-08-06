"""Truth boundaries for tool-required turns.

This module is intentionally text-only and fail-open.  It gives prompt and
output paths the same vocabulary for a required tool call, a successful result,
and a failed/unknown result.
"""

from __future__ import annotations

import re


GROUNDING_LAYER = "11_tool_grounding"

_COMPLETION_CLAIM_RE = re.compile(
    r"(?:已经|已|刚刚|刚才|现在已经|已经帮你|已帮你)"
    r"(?:查到|查过|搜到|搜过|看过|读到|读过|控制|操作|完成|打开|关闭|发送|发出|"
    r"播放|暂停|浇过|浇了|写入|更新|删除|清空|执行)"
    r"|(?:查到了|搜到了|看到了|读到了|控制好了|操作完成了|完成了|打开了|"
    r"关闭了|发送了|发出去了|正在播放)",
)


def grounding_message(
    *,
    required: bool,
    tool_names: list[str] | set[str] | tuple[str, ...] = (),
    result_validity: str = "none",
) -> dict | None:
    if not required:
        return None
    names = sorted({str(name) for name in tool_names if str(name)})
    name_text = "、".join(names) if names else "可用工具"
    if result_validity == "current_turn":
        content = (
            "【本轮工具事实】本轮已收到成功的工具结果；只依据边界内结果回答，"
            "不要把历史操作当成本轮结果。"
        )
    elif result_validity in {"execution_failed", "outcome_unknown"}:
        content = (
            f"【本轮工具事实】用户明确要求本轮使用{name_text}。当前调用没有得到可确认的成功结果，"
            "不得声称已经查到、控制、完成或执行；请如实说明未完成或结果不明。"
        )
    else:
        content = (
            f"【本轮工具事实】用户明确要求本轮使用{name_text}。必须先实际调用可用工具并取得成功结果，"
            "再回答事实；只有口头承诺、历史痕迹或模型自述都不算调用。调用失败/未暴露时，"
            "不得声称已经查到、控制、完成或执行。"
        )
    return {
        "role": "system",
        "content": content,
        "_layer": GROUNDING_LAYER,
        "_tool_grounding": {
            "required": True,
            "tool_names": names,
            "result_validity": result_validity,
        },
    }


def required_from_messages(messages: list[dict]) -> dict | None:
    for message in messages:
        if message.get("_layer") == GROUNDING_LAYER:
            data = message.get("_tool_grounding")
            if isinstance(data, dict) and data.get("required"):
                return data
    return None


def has_successful_tool_message(messages: list[dict]) -> bool:
    """Recognize only dispatcher success envelopes, never arbitrary model text."""
    for message in messages:
        if message.get("role") != "tool":
            continue
        content = str(message.get("content") or "")
        if "工具已执行：" in content and "<<<TOOL_DATA_START>>>" in content:
            return True
    return False


def guard_completion_claim(
    reply: str,
    messages: list[dict],
    *,
    successful_tool_call: bool | None = None,
) -> str:
    """Prevent completion claims when a required call did not succeed."""
    if not reply:
        return reply
    grounding = required_from_messages(messages)
    if not grounding:
        return reply
    validity = str(grounding.get("result_validity") or "none")
    succeeded = successful_tool_call
    if succeeded is None:
        succeeded = validity == "current_turn" or has_successful_tool_message(messages)
    if succeeded or not _COMPLETION_CLAIM_RE.search(reply):
        return reply
    return "我还没能实际完成这一步，刚才没有拿到可确认的成功结果。"

