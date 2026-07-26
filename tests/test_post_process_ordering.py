"""
post_process 顺序保证与超时降级测试

测试1 — critical writes 先完成：
  post_process 返回时 short_term / event_log / mood_state.update 已落盘。
  slow 任务（summarize_to_midterm）被 asyncio.Event 门控住，
  证明：在该任务被人为卡住期间，critical 数据已可读。

测试2 — detect_emotion 超时降级：
  detect_emotion 超过 _DETECT_EMOTION_TIMEOUT 未响应时，
  emotion 降级为 "neutral"，不向调用方抛出异常。
"""

import asyncio
from unittest.mock import AsyncMock

import pytest


class _MockCharacter:
    name = "Companion"


# ═══════════════════════════════════════════════════════════════════════════════
# 测试1：critical path 先完成，slow task 后完成
# ═══════════════════════════════════════════════════════════════════════════════

async def test_critical_writes_complete_before_slow_tasks(sandbox, monkeypatch, tmp_path):
    """
    语义：在 episodic 任务被 Event 门控住期间，critical 数据已经落盘可读。
    不是"先 await 再立刻读"——handler 被确定性地阻塞在 gate.wait()，
    因此 assert not marker.exists() 是确定性的，不依赖调度时序。
    """
    import core.post_process.slow_queue as sq
    from core.memory import short_term
    from core.pipeline import Pipeline

    uid = "uid_order_test"
    reply = "hi"  # len < 10 → _parse_and_execute_intent 提前返回，无需 mock chat

    # ── LLM 桩 ───────────────────────────────────────────────────────────────
    monkeypatch.setattr("core.llm_client.detect_emotion", AsyncMock(return_value="happy"))
    monkeypatch.setattr("core.llm_client.chat", AsyncMock(return_value=""))

    # 捕获 mood_state.update 调用（不依赖 weighted drift 的具体返回值）
    mood_calls: list[str] = []

    def _capture_mood(emotion, *args, **kwargs):
        mood_calls.append(emotion)

    monkeypatch.setattr("core.memory.mood_state.update", _capture_mood)

    # ── 门控式 slow task handler ──────────────────────────────────────────────
    # gate 打开前，handler 确定性地阻塞在 gate.wait()，
    # 使 assert not marker.exists() 不依赖调度时序。
    gate = asyncio.Event()
    marker = tmp_path / "episodic_done.txt"

    async def gated_slow(*_):
        await gate.wait()          # 门控：gate.set() 前确定性阻塞
        marker.write_text("done")

    # post_process 现在入队 summarize_to_midterm（新固化链路），用它做门控
    sq.register_handler("summarize_to_midterm", gated_slow)
    sq.register_handler("consistency_check",    AsyncMock())
    sq.start_worker()

    # ── 调用 post_process ─────────────────────────────────────────────────────
    from core.write_envelope import stamp_user_chat
    pipeline = Pipeline(_MockCharacter(), lore_engine=None)
    await pipeline.post_process(uid, "你好吗", reply, target_id="", is_group=False, envelope=stamp_user_chat())

    # 让 worker 有机会启动 handler（但 gate 关闭，marker 绝对未写入）
    await asyncio.sleep(0)

    # ── critical 写入验证 ─────────────────────────────────────────────────────
    history = short_term.load(uid)
    assert len(history) == 2, f"short_term 应有 user+assistant 共 2 条，实际: {len(history)}"
    assert history[0]["role"] == "user"
    assert history[0]["content"] == "你好吗"
    assert history[1]["role"] == "assistant"
    assert history[1]["content"] == reply

    # event_log 今日文件应含 user 行 + assistant 行。
    # Brief 37：capture_turn 现在跑在 post_process_critical（send 前的关键段），
    # 此时 detect_emotion 还没跑完，emotion 字段写死占位值 "neutral"——真实值
    # "happy" 只进 mood_state（下面的 mood_calls 断言），不回写 event_log 标注。
    from core.sandbox import get_paths
    # S6 新布局：event_log 写到 user_memory_root(uid) / "event_log"
    day_dir = get_paths().user_memory_root(uid) / "event_log"
    assert day_dir.exists(), "event_log 目录未创建"
    day_files = [f for f in day_dir.glob("*.md") if f.name != "full_log.md"]
    assert day_files, "event_log 今日文件未创建"
    log_text = day_files[0].read_text(encoding="utf-8")
    assert "你好吗" in log_text,          "user 行缺失"
    assert reply in log_text,            "assistant 行缺失"
    assert "emotion:neutral" in log_text, "assistant 行 emotion 占位字段缺失"

    # 深夜的 time_sleepiness 允许先写 sleepy；detect_emotion 的结果仍须成为
    # 本轮最终 mood write，不能把合法前置写入误判为顺序回归。
    assert mood_calls and mood_calls[-1] == "happy", \
        f"mood_state.update 最后一笔应为 'happy'，实际: {mood_calls}"

    # ── gate 关闭状态：episodic 确定性地尚未完成 ─────────────────────────────
    assert not marker.exists(), "gate 关闭期间 episodic 不应完成"

    # ── 打开 gate → drain → slow task 完成 ───────────────────────────────────
    gate.set()
    await sq.drain()
    assert marker.exists(), "drain 后 episodic 应已完成"


# ═══════════════════════════════════════════════════════════════════════════════
# 测试1.5（Brief 34 §1）：detect_emotion 在 uid_lock 外执行
# ═══════════════════════════════════════════════════════════════════════════════

async def test_detect_emotion_runs_outside_uid_lock(sandbox, monkeypatch):
    """detect_emotion 执行期间 uid_lock 不应被持有：用 Event 把 detect_emotion
    挂住，探测此时 uid_lock(uid).locked() 是否为 False，证明锁外算已生效。
    emotion 结果仍应正确写入 mood/event_log（在 gate 放行后完成）。
    """
    import core.post_process.slow_queue as sq
    from core.memory import locks as _locks
    from core.pipeline import Pipeline
    from core.sandbox import get_paths

    uid = "uid_lock_scope_test"

    detect_started = asyncio.Event()
    release_detect = asyncio.Event()

    async def gated_detect(*_):
        detect_started.set()
        await release_detect.wait()
        return "happy"

    monkeypatch.setattr("core.llm_client.detect_emotion", gated_detect)
    monkeypatch.setattr("core.llm_client.chat", AsyncMock(return_value=""))

    mood_calls: list[str] = []

    def _capture_mood(emotion, *args, **kwargs):
        mood_calls.append(emotion)

    monkeypatch.setattr("core.memory.mood_state.update", _capture_mood)

    sq.register_handler("summarize_to_midterm", AsyncMock())
    sq.register_handler("consistency_check", AsyncMock())
    sq.start_worker()

    from core.write_envelope import stamp_user_chat
    pipeline = Pipeline(_MockCharacter(), lore_engine=None)

    task = asyncio.create_task(
        pipeline.post_process(uid, "你好", "hi", target_id="", is_group=False, envelope=stamp_user_chat())
    )

    await asyncio.wait_for(detect_started.wait(), timeout=2)
    lock = _locks.uid_lock(uid)
    assert not lock.locked(), (
        "detect_emotion 挂起期间 uid_lock 被持有 —— 应挪到锁外算，锁内只做读-改-写"
    )

    release_detect.set()
    await task

    # Brief 37：capture_turn 跑在 post_process_critical（detect_emotion 之前），
    # event_log 的 emotion 字段是占位值 "neutral"；真实检测结果 "happy" 只进
    # post_process_slow 里的 mood_state.update，用 mood_calls 断言。
    day_dir = get_paths().user_memory_root(uid) / "event_log"
    day_files = [f for f in day_dir.glob("*.md") if f.name != "full_log.md"]
    assert day_files, "event_log 今日文件未创建"
    log_text = day_files[0].read_text(encoding="utf-8")
    assert "emotion:neutral" in log_text, f"event_log 应写占位值 neutral，实际:\n{log_text}"
    assert mood_calls and mood_calls[-1] == "happy", (
        f"detect_emotion 的真实结果应写入本轮最终 mood_state，实际: {mood_calls}"
    )

    await sq.drain()


# ═══════════════════════════════════════════════════════════════════════════════
# 测试2：detect_emotion 超时 → neutral 降级
# ═══════════════════════════════════════════════════════════════════════════════

async def test_detect_emotion_timeout_falls_back_to_neutral(sandbox, monkeypatch):
    import core.post_process.slow_queue as sq
    import core.pipeline as _pipeline_mod
    from core.pipeline import Pipeline
    from core.sandbox import get_paths

    uid = "uid_timeout_test"

    # 超时阈值压到 0.05s，detect_emotion 睡 0.2s → 必然触发 TimeoutError
    monkeypatch.setattr(_pipeline_mod, "_DETECT_EMOTION_TIMEOUT", 0.05)

    async def slow_detect(*_):
        await asyncio.sleep(0.2)
        return "happy"   # 不应到达这里

    monkeypatch.setattr("core.llm_client.detect_emotion", slow_detect)
    monkeypatch.setattr("core.llm_client.chat", AsyncMock(return_value=""))

    mood_calls: list[str] = []

    def _capture_mood(emotion, *args, **kwargs):
        mood_calls.append(emotion)

    monkeypatch.setattr("core.memory.mood_state.update", _capture_mood)

    sq.register_handler("consistency_check", AsyncMock())
    sq.start_worker()

    pipeline = Pipeline(_MockCharacter(), lore_engine=None)

    from core.write_envelope import stamp_user_chat
    # 不应向调用方抛出异常
    await pipeline.post_process(uid, "你好", "hi", target_id="", is_group=False, envelope=stamp_user_chat())

    # event_log assistant 行应含 emotion:neutral
    day_dir = get_paths().user_memory_root(uid) / "event_log"
    day_files = [f for f in day_dir.glob("*.md") if f.name != "full_log.md"]
    assert day_files, "event_log 今日文件未创建"
    log_text = day_files[0].read_text(encoding="utf-8")
    assert "emotion:neutral" in log_text, \
        f"超时降级时应为 emotion:neutral，实际:\n{log_text}"

    # 同上：sleepy 合法地先于 timeout fallback；最终值必须是 neutral。
    assert mood_calls and mood_calls[-1] == "neutral", \
        f"mood_state.update 最后一笔应为 'neutral'，实际: {mood_calls}"

    await sq.drain()
