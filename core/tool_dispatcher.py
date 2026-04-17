"""
工具调度模块
管理所有内置工具的注册、权限校验、执行和结果返回。
工具结果注入 prompt，不直接拼接进回复。

工具实现独立在 core/tools/ 子包中：
  core/tools/weather.py   — 天气查询
  core/tools/web_search.py — DuckDuckGo 搜索
设备控制和定时器逻辑较简单，直接写在此模块内。
"""

import logging
import platform
import subprocess
from typing import Callable

from core.config_loader import get_config
from core.error_handler import log_error

logger = logging.getLogger(__name__)

# ─── 工具注册表 ────────────────────────────────────────────────────────────────
_TOOL_REGISTRY: dict[str, dict] = {}

# 定时任务回调：由 main.py 注入，用于 set_timer 发送 QQ 消息
_send_callback: Callable | None = None


def register_send_callback(callback: Callable):
    """注入发送消息的回调函数（由 main.py 在初始化时调用）"""
    global _send_callback
    _send_callback = callback


# ─── 内联工具实现（设备控制、定时器）─────────────────────────────────────────

async def _device_shutdown(delay_seconds: int = 60) -> str:
    try:
        system = platform.system()
        if system == "Windows":
            subprocess.Popen(["shutdown", "/s", "/t", str(delay_seconds)])
        elif system in ("Linux", "Darwin"):
            subprocess.Popen(["shutdown", "-h", f"+{delay_seconds // 60}"])
        else:
            return f"不支持的系统平台：{system}"
        return f"已设置 {delay_seconds} 秒后关机"
    except Exception as e:
        log_error("tool.device_shutdown", e)
        return "关机命令执行失败"


async def _device_sleep() -> str:
    try:
        system = platform.system()
        if system == "Windows":
            subprocess.Popen(["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"])
        elif system == "Darwin":
            subprocess.Popen(["pmset", "sleepnow"])
        elif system == "Linux":
            subprocess.Popen(["systemctl", "suspend"])
        else:
            return f"不支持的系统平台：{system}"
        return "设备即将进入睡眠状态"
    except Exception as e:
        log_error("tool.device_sleep", e)
        return "睡眠命令执行失败"


# ─── 工具注册 ──────────────────────────────────────────────────────────────────

async def _get_current_time() -> str:
    from datetime import datetime
    now = datetime.now()
    week = ["一", "二", "三", "四", "五", "六", "日"][now.weekday()]
    return now.strftime(f"%Y年%m月%d日 %H:%M 星期{week}")


async def _add_reminder_wrapper(user_id: str, content: str, remind_at: str) -> str:
    from core.tools.reminder import add_reminder
    return add_reminder(user_id, content, remind_at)


def _weather_wrapper(city: str):
    from core.tools.weather import get_weather
    return get_weather(city)


def _web_search_wrapper(query: str):
    from core.tools.web_search import search
    return search(query)


_TOOL_REGISTRY["get_time"] = {
    "func": _get_current_time,
    "description": "获取当前准确时间，当用户询问时间、日期时调用.不确定时间时优先调用此工具,禁止猜测。",
    "dangerous": False,
    "parameters": {
        "type": "object",
        "properties": {},
        "required": [],
    },
}

_TOOL_REGISTRY["add_reminder"] = {
    "func": _add_reminder_wrapper,
    "description": (
    "添加一条备忘录，在指定时间提醒用户。"
    "当用户说'提醒我X点做Y'、'X时间记得Y'、'帮我记一下'时使用。"
    ),
    "dangerous": False,
    "parameters": {
        "type": "object",
        "properties": {
            "content": {
                "type": "string",
                "description": "要提醒的事项内容",
            },
            "remind_at": {
                "type": "string",
                "description": "提醒时间，格式：HH:MM 或 MM-DD HH:MM 或 YYYY-MM-DD HH:MM",
            },
        },
        "required": ["content", "remind_at"],
    },
}

_TOOL_REGISTRY["weather"] = {
    "func": _weather_wrapper,
    "description": "查询指定城市的当前天气。用户没有指定城市时，使用用户画像中的location字段，默认城市为杭州。",
    "dangerous": False,
    "parameters": {
        "type": "object",
        "properties": {
            "city": {"type": "string", "description": "城市名称，如 '北京' 或 'Beijing'"},
        },
        "required": ["city"],
    },
}

_TOOL_REGISTRY["device_shutdown"] = {
    "func": _device_shutdown,
    "description": "关闭设备（电脑关机）",
    "dangerous": True,
    "parameters": {
        "type": "object",
        "properties": {
            "delay_seconds": {
                "type": "integer",
                "description": "延迟多少秒后关机，默认60秒",
            },
        },
        "required": [],
    },
}

_TOOL_REGISTRY["device_sleep"] = {
    "func": _device_sleep,
    "description": "让设备进入睡眠/休眠状态",
    "dangerous": True,
    "parameters": {
        "type": "object",
        "properties": {},
        "required": [],
    },
}

_TOOL_REGISTRY["web_search"] = {
    "func": _web_search_wrapper,
    "description": "在网上查找信息，当你想确认某件事或帮用户找资料时使用",
    "dangerous": False,
    "parameters": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "搜索关键词或问题"},
        },
        "required": ["query"],
    },
}


# ─── 对外接口 ──────────────────────────────────────────────────────────────────

def _is_tool_enabled(tool_name: str) -> bool:
    """检查 config.yaml tools 配置中工具是否启用（默认启用）"""
    cfg = get_config().get("tools", {})
    group = tool_name
    if tool_name in ("device_shutdown", "device_sleep"):
        group = "device_control"
    elif tool_name == "set_timer":
        group = "timer"
    elif tool_name == "add_reminder":
        group = "reminder"
    return cfg.get(group, {}).get("enabled", True)


def get_tools_schema() -> list[dict]:
    """返回所有已启用工具的 OpenAI function_calling 格式 schema"""
    schemas = []
    for name, info in _TOOL_REGISTRY.items():
        if not _is_tool_enabled(name):
            continue
        schemas.append({
            "type": "function",
            "function": {
                "name": name,
                "description": info["description"],
                "parameters": info["parameters"],
            },
        })
    return schemas


async def execute(
    tool_name: str,
    tool_args: dict,
    user_id: str,
    target_id: str,
    is_group: bool,
    session_state,
) -> tuple[str | None, str | None]:
    """
    执行工具，返回 (tool_result, ask_confirm_text)

    tool_result:      工具执行结果字符串，None 表示无结果
    ask_confirm_text: 高危工具等待确认时的询问文字，None 表示无需确认
    """
    from core import user_relation

    from core.error_handler import get_tool_fail_response

    if tool_name not in _TOOL_REGISTRY:
        return get_tool_fail_response(), None

    if not _is_tool_enabled(tool_name):
        return get_tool_fail_response(), None

    tool_info = _TOOL_REGISTRY[tool_name]

    # 权限校验
    if tool_name in ("device_shutdown", "device_sleep"):
        if not user_relation.has_permission(user_id, "agent_control"):
            return "你没有执行此操作的权限哦", None

    # 高危工具确认机制
    if tool_info["dangerous"]:
        if session_state.status != session_state.WAITING_CONFIRM:
            session_state.set_waiting_confirm(tool_name, tool_args)
            return None, _build_confirm_ask(tool_name, tool_args)

    # 执行工具
    try:
        func = tool_info["func"]
        if tool_name == "add_reminder":
            result = await func(user_id=user_id, **tool_args)
        else:
            result = await func(**tool_args)
        logger.info(f"[tool_dispatcher] 工具 {tool_name} 执行完毕，结果: {result}")
        return f"工具已执行：{tool_name}，结果：{result}", None
    except TypeError as e:
        log_error("tool_dispatcher.execute", e)
        return get_tool_fail_response(), None
    except Exception as e:
        log_error("tool_dispatcher.execute", e)
        return get_tool_fail_response(), None


def _build_confirm_ask(tool_name: str, tool_args: dict) -> str:
    descriptions = {
        "device_shutdown": f"关机（{tool_args.get('delay_seconds', 60)}秒后）",
        "device_sleep": "让设备进入睡眠",
    }
    action = descriptions.get(tool_name, tool_name)
    return f"你确定要{action}吗？回复\"确认\"来执行，回复其他内容取消。"


class ToolDispatcher:
    """工具调度类封装，供外部按类方式导入使用"""

    def register_send_callback(self, callback):
        register_send_callback(callback)

    def get_tools_schema(self) -> list:
        return get_tools_schema()

    async def execute(self, tool_name, tool_args, user_id, target_id, is_group, session_state):
        return await execute(
            tool_name=tool_name,
            tool_args=tool_args,
            user_id=user_id,
            target_id=target_id,
            is_group=is_group,
            session_state=session_state,
        )
