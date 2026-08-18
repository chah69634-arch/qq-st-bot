"""
tests/test_event_log_source_tag.py — Brief 79 §1 event_log 来源标记

覆盖：
  1. event_log.append(source=...) 把 source: 写进 assistant / user 行的 meta。
  2. 不传 source（老调用方式）→ meta 不含 source 字段，行为完全不变（回归）。
  3. fixation_pipeline.capture_turn(source=...) 透传给 event_log.append。
"""
from __future__ import annotations
import asyncio
from tests.fixtures.public_assets import TEST_CHAR_ID

from core.memory import event_log
from core.memory.event_log_source import filter_recallable_text


def _day_text(sandbox, uid: str, char_id: str = TEST_CHAR_ID) -> str:
    day_dir = sandbox.memory_char_root(char_id=char_id) / uid / "event_log"
    files = [f for f in day_dir.glob("*.md") if f.name != "full_log.md"]
    assert len(files) == 1, f"期望恰好一个按天日志文件，实际 {len(files)} 个"
    return files[0].read_text(encoding="utf-8")


def test_append_assistant_with_source_writes_meta_field(sandbox):
    uid = "u_source_web"
    event_log.append(uid, "user", "帮我查一下天气", char_id=TEST_CHAR_ID)
    event_log.append(uid, "assistant", "查到了，明天晴", char_id=TEST_CHAR_ID, source="web")

    text = _day_text(sandbox, uid)
    assert "source:web" in text


def test_append_user_line_with_source_writes_meta_field(sandbox):
    uid = "u_source_user_line"
    event_log.append(uid, "user", "触发内容", char_id=TEST_CHAR_ID, source="dream_echo")

    text = _day_text(sandbox, uid)
    assert "source:dream_echo" in text


def test_append_without_source_omits_field(sandbox):
    """老调用方式（不传 source）→ meta 无 source 字段，回归保证。"""
    uid = "u_source_default"
    event_log.append(uid, "user", "普通一轮", char_id=TEST_CHAR_ID)
    event_log.append(uid, "assistant", "普通回复", char_id=TEST_CHAR_ID)

    text = _day_text(sandbox, uid)
    assert "source:" not in text


def test_capture_turn_forwards_source_to_event_log(sandbox):
    from core.memory.fixation_pipeline import capture_turn
    from core.write_envelope import WriteEnvelope

    uid = "u_capture_source"
    capture_turn(
        uid, "用户说了什么", "角色回了什么",
        envelope=WriteEnvelope(can_write_memory=True),
        char_id=TEST_CHAR_ID, source="coplay",
    )

    text = _day_text(sandbox, uid)
    assert "source:coplay" in text


def test_search_filters_isolated_and_unknown_blocks_before_scoring(sandbox):
    uid = "event-log-source-search"
    event_log.append(uid, "user", "ordinary-anchor", char_id=TEST_CHAR_ID)
    event_log.append(uid, "assistant", "ordinary-answer", char_id=TEST_CHAR_ID)
    event_log.append(uid, "user", "web-secret-anchor", char_id=TEST_CHAR_ID, source="web")
    event_log.append(uid, "assistant", "web-secret-answer", char_id=TEST_CHAR_ID, source="web")
    event_log.append(uid, "user", "unknown-secret-anchor", char_id=TEST_CHAR_ID, source="unregistered")

    ordinary, ordinary_trace = asyncio.run(event_log.search(
        uid, "ordinary-anchor", char_id=TEST_CHAR_ID, return_trace=True,
    ))
    isolated, isolated_trace = asyncio.run(event_log.search(
        uid, "web-secret-anchor", char_id=TEST_CHAR_ID, return_trace=True,
    ))
    unknown, unknown_trace = asyncio.run(event_log.search(
        uid, "unknown-secret-anchor", char_id=TEST_CHAR_ID, return_trace=True,
    ))

    assert "ordinary-anchor" in ordinary
    assert ordinary_trace
    assert "web-secret" not in isolated and isolated_trace == []
    assert "unknown-secret" not in unknown and unknown_trace == []


def test_old_event_log_vector_blob_cannot_boost_ranking(sandbox, monkeypatch):
    uid = "event-log-old-vector"
    event_log.append(uid, "user", "unrelated ordinary text", char_id=TEST_CHAR_ID)

    async def old_blob(*_args, **_kwargs):
        return [(f"recent:{uid}", 0.0, 1.0)]

    monkeypatch.setattr("core.memory.vector_store.query_async", old_blob)
    result, trace = asyncio.run(event_log.search(
        uid, "missing semantic target", char_id=TEST_CHAR_ID,
        return_trace=True, query_vec=[1.0],
    ))
    assert result == ""
    assert trace == []


def test_cross_date_source_filter_does_not_swallow_next_date_header():
    text = (
        "# 2026-08-01\n## 23:59\n**user**: isolated\n> speaker:user source:web\n---\n"
        "# 2026-08-02\n## 00:01\n**user**: retained\n> speaker:user\n---\n"
    )
    filtered, skipped = filter_recallable_text(text)
    assert skipped == 1
    assert "2026-08-01" not in filtered
    assert "isolated" not in filtered
    assert "# 2026-08-02" in filtered
    assert "retained" in filtered
