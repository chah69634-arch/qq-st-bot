"""
主动行为调度器
统一管理所有定时触发和事件触发的主动消息

触发源：
  时间触发 — 早安（7-9点）、晚安催睡（23点后）、随机日间消息（10-18点）
  Watch 触发 — 心率>100、心率>120、睡眠结束
  天气触发 — 暴雨/高温时主动提醒
"""

import asyncio
import logging
import random
import re
import time
from datetime import datetime, date
from typing import Optional

from core.error_handler import log_error

logger = logging.getLogger(__name__)

# ── Pipeline 注入（由 main.py 调用 set_pipeline 写入）────────────────────────
_pipeline = None


def set_pipeline(p):
    global _pipeline
    _pipeline = p


# ── 冷却时间（秒）────────────────────────────────────────────────────────────
_COOLDOWNS: dict[str, int] = {
    "morning_greeting":  8 * 3600,   # 早安：8小时（日触发一次）
    "night_reminder":    5 * 3600,   # 晚安：5小时
    "random_message":   14 * 3600,   # 随机日间：14小时（日触发一次）
    "hr_high":          30 * 60,     # 心率>100：30分钟
    "hr_critical":      60 * 60,     # 心率>120：1小时
    "sleep_end":         2 * 3600,   # 睡眠结束：2小时
    "weather_alert":     6 * 3600,   # 特殊天气：6小时
}

# 冷却跟踪 {trigger_name: last_unix_timestamp}
_last_trigger: dict[str, float] = {}

# 调度器 task 句柄
_scheduler_task: Optional[asyncio.Task] = None


# ═══════════════════════════════════════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════════════════════════════════════

def _cfg() -> dict:
    from core.config_loader import get_config
    return get_config().get("scheduler", {})


def _is_ready(name: str) -> bool:
    """检查触发器是否已度过冷却期"""
    elapsed = time.time() - _last_trigger.get(name, 0)
    return elapsed >= _COOLDOWNS.get(name, 3600)


def _mark(name: str):
    """记录触发时间"""
    _last_trigger[name] = time.time()


def _owner_id() -> str:
    return str(_cfg().get("owner_id", "")).strip()


async def _send(content: str):
    """向 owner 发私聊消息"""
    oid = _owner_id()
    if not oid:
        logger.warning("[scheduler] owner_id 未配置，跳过发送")
        return
    from core import qq_adapter
    await qq_adapter.send_message(oid, content, is_group=False)


async def _pipeline_send(prompt: str):
    """通过 Pipeline 生成角色回复，再向 owner 发送。
    Pipeline 未注入时降级直接发送 prompt 原文并打 warning。
    """
    oid = _owner_id()
    if not oid:
        logger.warning("[scheduler._pipeline_send] owner_id 未配置，跳过")
        return
    try:
        if _pipeline is None:
            logger.warning("[scheduler._pipeline_send] pipeline 未注入，降级直接发送")
            await _send(prompt)
            return

        context = await _pipeline.fetch_context(oid, prompt)
        messages = _pipeline.build_prompt(oid, prompt, context)
        reply    = await _pipeline.run_llm(messages)
        if reply:
            await _send(reply)
            asyncio.create_task(
                _pipeline.post_process(oid, prompt, reply)
            )
        else:
            logger.warning("[scheduler._pipeline_send] LLM 返回空内容")
    except Exception as e:
        log_error("scheduler._pipeline_send", e)


def _user_talked_today(user_id: str) -> bool:
    """检查用户今天在事件日志中是否有记录"""
    from pathlib import Path
    today = date.today().strftime("%Y-%m-%d")
    p = Path(f"data/event_log/{user_id}/{today}.md")
    return p.exists() and p.stat().st_size > 10


# ═══════════════════════════════════════════════════════════════════════════════
# 时间触发
# ═══════════════════════════════════════════════════════════════════════════════

async def _check_morning(force: bool = False):
    """早安触发：7-9点，且 owner 今天还没说过话。force=True 跳过时间和对话检查"""
    cfg = _cfg()
    if not cfg.get("morning_greeting", True):
        return
    if not _is_ready("morning_greeting"):
        return

    if not force:
        now = datetime.now()
        if not (7 <= now.hour < 9):
            return
        oid = _owner_id()
        if oid and _user_talked_today(oid):
            return

    await _pipeline_send("（清晨，叶瑄看了看时间，想起你应该快起床了）")
    _mark("morning_greeting")
    logger.info("[scheduler] 早安消息已发送")


async def _check_night(force: bool = False):
    """晚安催睡：23点后。force=True 跳过时间检查"""
    cfg = _cfg()
    if not cfg.get("night_reminder", True):
        return
    if not _is_ready("night_reminder"):
        return

    if not force:
        now = datetime.now()
        if now.hour < 23:
            return

    await _pipeline_send("（深夜，叶瑄注意到时间很晚了，想到你还没睡）")
    _mark("night_reminder")
    logger.info("[scheduler] 晚安消息已发送")


async def _check_random_message(force: bool = False):
    """随机日间消息：10-18点，每天随机触发一次。force=True 跳过时间和概率检查"""
    cfg = _cfg()
    if not cfg.get("random_message", True):
        return
    if not _is_ready("random_message"):
        return

    if not force:
        now = datetime.now()
        if not (10 <= now.hour < 18):
            return
        # 一天可用窗口约 480 分钟，每 60 秒检查一次，平均触发 1 次
        if random.random() > (1 / 480):
            return

    await _pipeline_send("（叶瑄在做一件日常的事，忽然想到你）")
    _mark("random_message")
    logger.info("[scheduler] 随机日间消息已发送")


# ═══════════════════════════════════════════════════════════════════════════════
# Watch 事件触发（由 /watch 路由调用）
# ═══════════════════════════════════════════════════════════════════════════════

async def on_watch_event(event_type: str, data: dict):
    """
    接收 Watch 事件并触发主动行为。

    event_type:
        "heart_rate"  — data = {"value": int}
        "sleep_end"   — data = {}
    """
    cfg = _cfg()
    if not cfg.get("enabled", True):
        return
    if not _owner_id():
        return

    if event_type == "heart_rate":
        hr = int(data.get("value", 0))
        if hr > 120 and _is_ready("hr_critical"):
            await _pipeline_send(f"（叶瑄的手表显示你的心率{hr}，他皱了皱眉）")
            _mark("hr_critical")
            logger.info(f"[scheduler] 心率危急触发 hr={hr}")
        elif hr > 100 and _is_ready("hr_high"):
            await _pipeline_send(f"（叶瑄的手表显示你的心率{hr}，稍微有点高，他有些关心）")
            _mark("hr_high")
            logger.info(f"[scheduler] 心率偏高触发 hr={hr}")

    elif event_type == "sleep_end":
        if _is_ready("sleep_end"):
            await _pipeline_send("（叶瑄看到你的睡眠数据显示已经醒来）")
            _mark("sleep_end")
            logger.info("[scheduler] 睡眠结束触发")


# ═══════════════════════════════════════════════════════════════════════════════
# 天气触发
# ═══════════════════════════════════════════════════════════════════════════════

async def _check_weather():
    """天气触发：当 owner 所在城市有暴雨/高温时主动发一句"""
    from core.config_loader import get_config
    if not get_config().get("tools", {}).get("weather", {}).get("enabled", True):
        return
    cfg = _cfg()
    if not cfg.get("enabled", True):
        return
    if not _is_ready("weather_alert"):
        return

    oid = _owner_id()
    if not oid:
        return

    try:
        from core.memory.user_profile import load as _load_profile
        location = _load_profile(oid).get("location", "")
        if not location:
            return

        from core.tools.weather import get_weather
        weather_text = await get_weather(location)
        if not weather_text or "失败" in weather_text or "超时" in weather_text:
            return

        # 解析温度
        temp_match = re.search(r"[+\-]?(\d+)°?C", weather_text)
        temp = int(temp_match.group(1)) if temp_match else 0

        msg = None
        if any(k in weather_text for k in ("暴雨", "大雨", "雷暴", "storm", "rain")):
            msg = f"外面在下暴雨，出门记得带伞，路上小心"
        elif temp >= 35:
            msg = f"今天{temp}度，热死了，多喝水别中暑"
        elif temp <= 0:
            msg = f"今天零下{abs(temp)}度，出门一定要穿厚点"

        if msg:
            await _send(msg)
            _mark("weather_alert")
            logger.info(f"[scheduler] 天气提醒: {msg}")
    except Exception as e:
        log_error("scheduler._check_weather", e)


# ═══════════════════════════════════════════════════════════════════════════════
# 手动触发（供管理面板调用）
# ═══════════════════════════════════════════════════════════════════════════════

async def manual_trigger(name: str) -> str:
    """
    手动触发指定动作（绕过冷却时间检查）。
    返回结果描述字符串。
    """
    # (fn, cooldown_key, use_force) — 时间依赖函数传 force=True
    mapping = {
        "morning_greeting": (_check_morning,        "morning_greeting", True),
        "night_reminder":   (_check_night,          "night_reminder",   True),
        "random_message":   (_check_random_message, "random_message",   True),
    }
    if name not in mapping:
        return f"未知触发器: {name}"

    fn, cooldown_key, use_force = mapping[name]
    # 清零冷却，强制触发
    _last_trigger[cooldown_key] = 0
    try:
        await fn(force=True) if use_force else await fn()
        return f"{name} 已触发"
    except Exception as e:
        log_error(f"scheduler.manual_trigger.{name}", e)
        return f"{name} 触发失败: {e}"


# ═══════════════════════════════════════════════════════════════════════════════
# 主循环 & 启动
# ═══════════════════════════════════════════════════════════════════════════════

async def _loop():
    """调度器主循环，每 60 秒检查一次"""
    logger.info("[scheduler] 调度器已启动，每 60 秒检查一次")
    while True:
        try:
            cfg = _cfg()
            if cfg.get("enabled", True):
                await _check_morning()
                await _check_night()
                await _check_random_message()
                await _check_weather()
        except Exception as e:
            log_error("scheduler._loop", e)
        await asyncio.sleep(60)


def start() -> asyncio.Task:
    """启动调度器后台 Task，返回 Task 对象供 main.py 管理"""
    global _scheduler_task
    _scheduler_task = asyncio.create_task(_loop())
    logger.info("[scheduler] 调度器 Task 已创建")
    return _scheduler_task


# ═══════════════════════════════════════════════════════════════════════════════
# 状态查询（供管理面板）
# ═══════════════════════════════════════════════════════════════════════════════

def get_status() -> dict:
    """
    返回所有触发器的状态信息：
    {trigger_name: {last_triggered, cooldown_sec, remaining_sec, ready}}
    """
    now = time.time()
    result = {}
    for name, cooldown in _COOLDOWNS.items():
        last = _last_trigger.get(name, 0)
        elapsed = now - last if last > 0 else cooldown + 1
        remaining = max(0, cooldown - elapsed)
        result[name] = {
            "last_triggered": (
                datetime.fromtimestamp(last).strftime("%Y-%m-%d %H:%M:%S")
                if last > 0 else "从未"
            ),
            "cooldown_sec":   cooldown,
            "remaining_sec":  int(remaining),
            "ready":          remaining == 0,
        }
    return result
