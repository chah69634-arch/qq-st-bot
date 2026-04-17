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
    "period_reminder":  24 * 3600,   # 生理期关心：24小时
    "diary_reminder":   20 * 3600,   # 日记提醒：20小时
    "diary_inject":      6 * 3600,   # 日记注入：6小时
    "daily_journal":          1 * 3600,   # 每日手账：1小时冷却（深夜触发）
    "diary_share_reminder":  24 * 3600,   # 日记分享提醒：24小时
}

# 冷却跟踪 {trigger_name: last_unix_timestamp}
_last_trigger: dict[str, float] = {}

# 上次主动分享日记的时间戳（由 diary_tool 调用 mark_diary_shared 更新）
_last_diary_share: float = 0.0

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

    oid = _owner_id()

    # 读取最近event_log作为情境素材
    try:
        from core.memory.event_log import get_recent_days
        recent = get_recent_days(oid, days=2)
        if recent and len(recent) > 30:
            context_hint = f"最近和你聊过的内容（作为情境参考）：{recent[:400]}"
        else:
            context_hint = ""
    except Exception:
        context_hint = ""

    prompt = (
        f"（叶瑄在做一件日常的事，忽然想到你。"
        f"{'结合你们最近的对话，' if context_hint else ''}"
        f"用一句具体的、有温度的话表达这一刻的想法，不要说废话）"
        + (f"\n{context_hint}" if context_hint else "")
    )
    await _pipeline_send(prompt)
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
# 备忘录到点提醒
# ═══════════════════════════════════════════════════════════════════════════════

async def _check_reminders():
    """检查 owner 的备忘录是否有到点条目，有则发送提醒后标记完成"""
    cfg = _cfg()
    if not cfg.get("enabled", True):
        return
    oid = _owner_id()
    if not oid:
        return
    try:
        from core.tools.reminder import get_due_reminders, mark_done
        due = get_due_reminders(oid)
        for item in due:
            await _pipeline_send(
                f"备忘录提醒时间到了：{item['content']}，用叶瑄的方式提醒小画家"
            )
            mark_done(oid, item["id"])
            logger.info(f"[scheduler] 备忘录提醒已发送: {item['content']}")
    except Exception as e:
        log_error("scheduler._check_reminders", e)


# ═══════════════════════════════════════════════════════════════════════════════
# 生理期关心
# ═══════════════════════════════════════════════════════════════════════════════

async def _check_period():
    """读取 last_period_date，在生理期中（0-7天）或临近下次（26-30天）时关心"""
    cfg = _cfg()
    if not cfg.get("enabled", True):
        return
    oid = _owner_id()
    if not oid:
        return
    try:
        from core.memory.user_profile import get_period_info
        info = get_period_info(oid)
        last_date_str = info.get("last_period_date")
        if not last_date_str:
            return
        from datetime import datetime, date as _date
        last_date = datetime.strptime(last_date_str, "%Y-%m-%d").date()
        days_elapsed = (_date.today() - last_date).days
        # 第一段：生理期中关心（0-7天内，冷却24小时）
        if 0 <= days_elapsed <= 7:
            if _is_ready("period_reminder"):
                await _pipeline_send(
                    f"（叶瑄记得你的生理期已经来了{days_elapsed}天，悄悄关心一下，"
                    f"提醒避免冷饮，问问她今天状态怎么样）"
                )
                _mark("period_reminder")
                logger.info(f"[scheduler] 生理期中关心消息已发送，距上次 {days_elapsed} 天")

        # 第二段：下次预告（26-30天，冷却24小时）
        elif 26 <= days_elapsed <= 30:
            if _is_ready("period_reminder"):
                await _pipeline_send(
                    "（叶瑄注意到你的生理期大概要来了，悄悄关心一下）"
                )
                _mark("period_reminder")
                logger.info(f"[scheduler] 生理期预告消息已发送，距上次 {days_elapsed} 天")
    except Exception as e:
        log_error("scheduler._check_period", e)


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
        if not temp_match:
            return
        temp = int(temp_match.group(1))

        msg = None
        if any(k in weather_text for k in ("暴雨", "大雨", "雷暴", "storm", "rain")):
            msg = f"外面在下暴雨，出门记得带伞，路上小心"
        elif temp >= 35:
            msg = f"今天{temp}度，热死了，多喝水别中暑"
        elif temp <= -5:
            msg = f"今天零下{abs(temp)}度，出门一定要穿厚点"

        if msg:
            await _pipeline_send(
                f"（叶瑄看了一眼天气预报，想到你——{msg}，用叶瑄的方式提醒她）"
            )
            _mark("weather_alert")
            logger.info(f"[scheduler] 天气提醒: {msg}")
    except Exception as e:
        log_error("scheduler._check_weather", e)


# ═══════════════════════════════════════════════════════════════════════════════
# 手动触发（供管理面板调用）
# ═══════════════════════════════════════════════════════════════════════════════

async def manual_trigger(name: str) -> str:
    """
    手动触发指定动作（绕过冷却时间和条件检查）。
    返回结果描述字符串。
    """
    _last_trigger[name] = 0  # 清零冷却

    try:
        if name == "morning_greeting":
            await _check_morning(force=True)
        elif name == "night_reminder":
            await _check_night(force=True)
        elif name == "random_message":
            await _check_random_message(force=True)
        elif name == "daily_journal":
            oid = _owner_id()
            if not oid:
                return "owner_id 未配置"
            from core.memory.event_log import get_recent_days
            today_log = get_recent_days(oid, days=1)
            log_hint = today_log[:800] if today_log and len(today_log) > 10 else "今天还没有对话记录"
            await _pipeline_send(
                f"（深夜，叶瑄回想起今天和小画家说过的话，提笔写下今天的感受——"
                f"今天的对话内容：{log_hint}）"
            )
            _mark("daily_journal")
        elif name == "period_reminder":
            oid = _owner_id()
            if not oid:
                return "owner_id 未配置"
            from core.memory.user_profile import get_period_info
            from datetime import date as _date
            info = get_period_info(oid)
            last_date_str = info.get("last_period_date")
            if last_date_str:
                last_date = datetime.strptime(last_date_str, "%Y-%m-%d").date()
                days_elapsed = (_date.today() - last_date).days
                await _pipeline_send(
                    f"（叶瑄记得小画家的生理期已经来了{days_elapsed}天，悄悄关心一下）"
                )
            else:
                await _pipeline_send("（叶瑄想关心一下小画家的身体状况）")
            _mark("period_reminder")
        elif name == "diary_reminder":
            oid = _owner_id()
            if not oid:
                return "owner_id 未配置"
            from datetime import date as _date, timedelta
            yesterday = (_date.today() - timedelta(days=1)).strftime("%m月%d日")
            await _pipeline_send(
                f"（叶瑄想起来，{yesterday}好像没看到小画家写日记）"
            )
            _mark("diary_reminder")
        elif name == "diary_share_reminder":
            oid = _owner_id()
            if not oid:
                return "owner_id 1043484516"
            await _pipeline_send(
                "（叶瑄想起来，好像很久没看到小画家的日记了，故作不经意地提一句）"
            )
            _mark("diary_share_reminder")
        else:
            return f"未知触发器: {name}"
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
                await _check_reminders()
                await _check_period()
                await _check_diary_reminder()
                await _check_diary_inject()
                await _check_daily_journal()
                await _check_diary_share_reminder()
        except Exception as e:
            log_error("scheduler._loop", e)
        await asyncio.sleep(60)


def start() -> asyncio.Task:
    """启动调度器后台 Task，返回 Task 对象供 main.py 管理"""
    global _scheduler_task
    _scheduler_task = asyncio.create_task(_loop())
    logger.info("[scheduler] 调度器 Task 已创建")
    return _scheduler_task


async def _check_diary_reminder():
    """昨天没写日记时，叶瑄提醒"""
    cfg = _cfg()
    if not cfg.get("enabled", True):
        return
    if not _is_ready("diary_reminder"):
        return
    now = datetime.now()
    if not (9 <= now.hour < 12):
        return
    try:
        from core.tools.diary_reader import yesterday_missing
        if yesterday_missing():
            from datetime import timedelta
            yesterday = (date.today() - timedelta(days=1)).strftime("%m月%d日")
            await _pipeline_send(
                f"（叶瑄想起来，{yesterday}好像没看到小画家写日记）"
            )
            _mark("diary_reminder")
            logger.info("[scheduler] 日记缺失提醒已发送")
    except Exception as e:
        log_error("scheduler._check_diary_reminder", e)


async def _check_diary_inject():
    """每6小时读取最近日记，注入到用户画像的event_log里"""
    cfg = _cfg()
    if not cfg.get("enabled", True):
        return
    if not _is_ready("diary_inject"):
        return
    oid = _owner_id()
    if not oid:
        return
    try:
        from core.tools.diary_reader import read_recent
        from core.memory.event_log import append
        text = read_recent(days=2)
        if text:
            append(oid, "user", f"【日记内容】\n{text}")
            _mark("diary_inject")
            logger.info("[scheduler] 日记内容已注入event_log")
    except Exception as e:
        log_error("scheduler._check_diary_inject", e)


async def _check_daily_journal():
    """每日手账：23点后，读取今天event_log，让叶瑄写一段心理活动发给你"""
    cfg = _cfg()
    if not cfg.get("enabled", True):
        return
    if not _is_ready("daily_journal"):
        return
    now = datetime.now()
    if now.hour < 23:
        return
    oid = _owner_id()
    if not oid:
        return
    try:
        from core.memory.event_log import get_recent_days
        today_log = get_recent_days(oid, days=1)
        if not today_log or len(today_log) < 50:
            return
        await _pipeline_send(
            f"（深夜，叶瑄回想起今天和小画家说过的话，提笔写下今天的感受——"
            f"今天的对话内容：{today_log[:800]}）"
        )
        _mark("daily_journal")
        logger.info("[scheduler] 每日手账已发送")
    except Exception as e:
        log_error("scheduler._check_daily_journal", e)


async def _check_diary_share_reminder():
    """超过3天没看到日记分享时，叶瑄不经意提一句"""
    cfg = _cfg()
    if not cfg.get("enabled", True):
        return
    if not _is_ready("diary_share_reminder"):
        return
    if time.time() - _last_diary_share < 259200:  # 3天内分享过就跳过
        return
    oid = _owner_id()
    if not oid:
        return
    try:
        await _pipeline_send(
            "（叶瑄想起来，好像很久没看到小画家的日记了，故作不经意地提一句）"
        )
        _mark("diary_share_reminder")
        logger.info("[scheduler] 日记分享提醒已发送")
    except Exception as e:
        log_error("scheduler._check_diary_share_reminder", e)


def mark_diary_shared():
    global _last_diary_share
    _last_diary_share = time.time()


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
