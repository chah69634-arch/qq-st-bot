"""
LLM 客户端模块
所有 LLM 调用的唯一出口，支持 DeepSeek / OpenAI / 本地模型
"""

import json
import logging
import re
from typing import Any

import httpx
from openai import AsyncOpenAI

from core.config_loader import get_config
from core.error_handler import log_error

logger = logging.getLogger(__name__)

# 全局客户端实例（延迟初始化）
_client: AsyncOpenAI | None = None


def _get_proxy_url() -> str | None:
    """读取代理配置，未启用时返回 None"""
    proxy_cfg = get_config().get("proxy", {})
    if proxy_cfg.get("enabled", False):
        return proxy_cfg.get("http") or None
    return None


def _get_client() -> AsyncOpenAI:
    """获取 OpenAI 客户端（单例，含代理配置）"""
    global _client
    if _client is None:
        cfg = get_config()["llm"]
        proxy_url = _get_proxy_url()
        http_client = httpx.AsyncClient(proxy=proxy_url) if proxy_url else None
        _client = AsyncOpenAI(
            api_key=cfg["api_key"],
            base_url=cfg["base_url"],
            http_client=http_client,
        )
        logger.info(
            f"[llm_client] 客户端已初始化，代理={'已启用 ' + proxy_url if proxy_url else '未启用'}"
        )
    return _client


def reload_client():
    """
    重置 OpenAI 客户端（代理/API Key 配置变更后调用）
    下次调用 _get_client() 时会重新按最新配置创建
    """
    global _client
    _client = None
    logger.info("[llm_client] 客户端已重置，下次请求时按最新配置重建")


async def chat(
    messages: list[dict],
    tools: list[dict] | None = None,
    max_tokens_override: int | None = None,
) -> str:
    """
    调用 LLM 生成回复

    参数:
        messages: OpenAI 格式的消息列表 [{role, content}, ...]
        tools:    工具定义列表（function_calling 模式时使用）

    返回:
        模型生成的文本字符串
        function_calling 模式下如果模型调用了工具，返回序列化后的工具调用 JSON
    """
    cfg = get_config()["llm"]
    client = _get_client()
    model = cfg["model"]
    mode = cfg.get("tool_call_mode", "function_calling")

    # 读取生成参数（每次 chat 调用都重新读，支持热重载）
    temperature       = float(cfg.get("temperature",       0.7))
    top_p             = float(cfg.get("top_p",             0.9))
    max_tokens        = max_tokens_override or int(cfg.get("max_tokens", 1000))
    frequency_penalty = float(cfg.get("frequency_penalty", 0.0))

    # 公共关键字参数，注入到每种调用模式
    _gen_kwargs = dict(
        temperature=temperature,
        top_p=top_p,
        max_tokens=max_tokens,
        frequency_penalty=frequency_penalty,
    )

    try:
        # ── function_calling 模式 ──────────────────────────────────────────
        if mode == "function_calling" and tools:
            response = await client.chat.completions.create(
                model=model,
                messages=messages,
                tools=tools,
                tool_choice="auto",
                **_gen_kwargs,
            )
            choice = response.choices[0]
            # 模型选择调用工具时，返回工具调用信息的 JSON 字符串
            if choice.finish_reason == "tool_calls" and choice.message.tool_calls:
                tool_calls = []
                for tc in choice.message.tool_calls:
                    tool_calls.append({
                        "name": tc.function.name,
                        "arguments": json.loads(tc.function.arguments),
                    })
                # 用特殊前缀标记，让 tool_dispatcher 识别
                return "__TOOL_CALL__:" + json.dumps(tool_calls, ensure_ascii=False)
            return choice.message.content or ""

        # ── xml_fallback 模式（不支持 FC 的模型）────────────────────────────
        elif mode == "xml_fallback" and tools:
            # 把工具描述注入到 system 消息末尾
            tool_desc = _build_xml_tool_desc(tools)
            msgs = list(messages)
            injected = False
            for i, m in enumerate(msgs):
                if m["role"] == "system":
                    msgs[i] = {
                        "role": "system",
                        "content": m["content"] + "\n\n" + tool_desc,
                    }
                    injected = True
                    break
            if not injected:
                msgs.insert(0, {"role": "system", "content": tool_desc})

            response = await client.chat.completions.create(
                model=model,
                messages=msgs,
                **_gen_kwargs,
            )
            return response.choices[0].message.content or ""

        # ── 普通对话（无工具）────────────────────────────────────────────────
        else:
            response = await client.chat.completions.create(
                model=model,
                messages=messages,
                **_gen_kwargs,
            )
            return response.choices[0].message.content or ""

    except Exception as e:
        log_error("llm_client.chat", e)
        raise


def parse_tool_call_response(response: str) -> list[dict] | None:
    """
    解析 LLM 返回值中的工具调用信息

    function_calling 模式：检测 __TOOL_CALL__: 前缀
    xml_fallback 模式：检测 <tool_call> 标签

    返回工具调用列表，无工具调用则返回 None
    """
    # function_calling 模式
    if response.startswith("__TOOL_CALL__:"):
        try:
            return json.loads(response[len("__TOOL_CALL__:"):])
        except json.JSONDecodeError:
            return None

    # xml_fallback 模式
    pattern = r"<tool_call>(.*?)</tool_call>"
    matches = re.findall(pattern, response, re.DOTALL)
    if matches:
        tool_calls = []
        for m in matches:
            try:
                data = json.loads(m.strip())
                tool_calls.append(data)
            except json.JSONDecodeError:
                pass
        return tool_calls if tool_calls else None

    return None


def _build_xml_tool_desc(tools: list[dict]) -> str:
    """为 xml_fallback 模式构建工具说明，注入到 system 消息"""
    lines = [
        "你可以使用以下工具。需要调用工具时，用如下格式输出（只输出 JSON，不要多余文字）：",
        "<tool_call>",
        '{"name": "工具名", "arguments": {"参数名": "参数值"}}',
        "</tool_call>",
        "",
        "可用工具：",
    ]
    for tool in tools:
        func = tool.get("function", tool)
        name = func.get("name", "")
        desc = func.get("description", "")
        params = func.get("parameters", {}).get("properties", {})
        param_str = ", ".join(
            f'{k}({v.get("type","any")})' for k, v in params.items()
        )
        lines.append(f"- {name}({param_str}): {desc}")
    return "\n".join(lines)


_VALID_EMOTIONS = frozenset({"neutral", "happy", "sad", "gentle", "surprised", "angry"})


async def detect_emotion(text: str) -> str:
    """
    轻量 LLM 调用，判断回复文本的情绪。
    只消耗约 10 个 token，异步非阻塞。
    返回值：neutral / happy / sad / gentle / surprised / angry
    失败时返回 "neutral"。
    """
    prompt = (
        "判断以下文本的情绪，只返回一个词：\n"
        "neutral/happy/sad/gentle/surprised/angry\n"
        f"文本：{text}"
    )
    try:
        cfg = get_config()["llm"]
        client = _get_client()
        response = await client.chat.completions.create(
            model=cfg["model"],
            messages=[{"role": "user", "content": prompt}],
            max_tokens=10,
            temperature=0.0,
        )
        result = (response.choices[0].message.content or "").strip().lower()
        return result if result in _VALID_EMOTIONS else "neutral"
    except Exception as e:
        log_error("llm_client.detect_emotion", e)
        return "neutral"


class LLMClient:
    """LLM 客户端类，封装模块级函数，供外部按类方式导入使用"""

    async def chat(self, messages: list, tools: list | None = None) -> str:
        return await chat(messages, tools)

    async def detect_emotion(self, text: str) -> str:
        return await detect_emotion(text)

    def parse_tool_call_response(self, response: str) -> list | None:
        return parse_tool_call_response(response)
