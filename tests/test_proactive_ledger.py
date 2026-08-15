"""CC 任务 19 · B — ProactiveLedger 单测。

覆盖 can_send/record_send 的间隔+预算双闸、emergency 豁免（仍记账）、
daily 计数按逻辑日重置、continuity_hint/snapshot 的 fail-open 行为。
"""

import pytest


@pytest.fixture(autouse=True)
def _isolated_ledger_state(sandbox, monkeypatch):
    """每个测试用全新内存状态 + 固定 config，避免跨测试污染或读取真实 config.yaml。"""
    from core.scheduler import proactive_ledger as ledger

    monkeypatch.setattr(ledger, "_state", {
        "next_allowed_ts": 0.0,
        "daily_count": 0,
        "daily_logical_day": "",
        "recent": [],
        "continuity_by_uid": {},
    })
    monkeypatch.setattr(ledger, "_loaded", True)  # 跳过磁盘加载，state 已就位
    monkeypatch.setattr(ledger, "_cfg", lambda: {
        "global_proactive_min_gap_seconds": 10,
        "max_daily_proactive": 2,
    })
    return ledger


def test_can_send_ok_when_never_sent(_isolated_ledger_state):
    ledger = _isolated_ledger_state
    ok, reason = ledger.can_send("random_message", priority="normal")
    assert ok
    assert reason == "ok"


def test_record_send_blocks_until_gap_elapses(_isolated_ledger_state):
    ledger = _isolated_ledger_state
    ledger.record_send("random_message", gist="随便说了句话")
    ok, reason = ledger.can_send("random_message", priority="normal")
    assert not ok
    assert reason == "gap_not_elapsed"


def test_emergency_bypasses_gap_but_still_records(_isolated_ledger_state):
    ledger = _isolated_ledger_state
    ledger.record_send("random_message", gist="x")
    # gap not elapsed for normal priority, but emergency is exempt
    ok, reason = ledger.can_send("hr_critical", priority="emergency")
    assert ok
    assert reason == "emergency_exempt"

    before = ledger.snapshot()["daily_count"]
    ledger.record_send("hr_critical", gist="心率危急")
    after = ledger.snapshot()["daily_count"]
    assert after == before + 1, "emergency 发送豁免限流但仍要记账（RC5）"


def test_daily_budget_exhausted_blocks_normal_but_not_emergency(_isolated_ledger_state):
    ledger = _isolated_ledger_state
    # 预算=2；连续两次发送后耗尽
    ledger.record_send("random_message", gist="a")
    ledger._state["next_allowed_ts"] = 0  # 跳过 gap，只测预算
    ledger.record_send("random_message", gist="b")
    ledger._state["next_allowed_ts"] = 0

    ok, reason = ledger.can_send("random_message", priority="normal")
    assert not ok
    assert reason == "daily_budget_exceeded"

    ok, reason = ledger.can_send("hr_critical", priority="emergency")
    assert ok
    assert reason == "emergency_exempt"


def test_daily_count_resets_on_new_logical_day(_isolated_ledger_state):
    ledger = _isolated_ledger_state
    ledger._state["daily_count"] = 2
    ledger._state["daily_logical_day"] = "2000-01-01"  # 远古日期，必定不等于今天

    ok, reason = ledger.can_send("random_message", priority="normal")
    assert ok
    assert reason == "ok"
    assert ledger.snapshot()["daily_count"] == 0


def test_record_send_keeps_last_three_recent_entries(_isolated_ledger_state):
    ledger = _isolated_ledger_state
    for i in range(5):
        ledger._state["next_allowed_ts"] = 0
        ledger.record_send(f"trigger_{i}", gist=f"gist_{i}")

    recent = ledger.snapshot()["recent"]
    assert len(recent) == 3
    assert [r["trigger_name"] for r in recent] == ["trigger_2", "trigger_3", "trigger_4"]


def test_continuity_hint_empty_when_no_recent(_isolated_ledger_state):
    ledger = _isolated_ledger_state
    assert ledger.continuity_hint() == ""


def test_continuity_hint_references_last_gist(_isolated_ledger_state):
    ledger = _isolated_ledger_state
    ledger.record_send("random_message", gist="想起了一件小事")
    hint = ledger.continuity_hint()
    assert "想起了一件小事" in hint
    assert "别重复" in hint


def test_snapshot_reflects_config_gap_and_budget(_isolated_ledger_state):
    ledger = _isolated_ledger_state
    snap = ledger.snapshot()
    assert snap["effective_gap_seconds"] == 10
    assert snap["daily_budget"] == 2
    assert snap["daily_count"] == 0


def test_continuity_cap_is_scoped_to_uid_and_empty_uid_keeps_owner_fallback(_isolated_ledger_state):
    ledger = _isolated_ledger_state
    ledger._cfg = lambda: {
        "global_proactive_min_gap_seconds": 0,
        "max_daily_proactive": 8,
        "owner_id": "owner-1",
    }

    ledger.record_send("owner_trigger", uid="owner-1")
    ledger.record_send("other_trigger", uid="owner-2")
    ledger.record_send("owner_trigger_2", uid="owner-1")

    allowed_owner, owner_reason = ledger.can_send("owner_trigger", uid="owner-1")
    allowed_other, other_reason = ledger.can_send("other_trigger", uid="owner-2")
    assert not allowed_owner and owner_reason == "unanswered_cap"
    assert allowed_other and other_reason == "ok"

    # Empty uid is a deliberate legacy compatibility boundary and resolves to
    # the configured owner rather than silently creating a global continuity row.
    allowed_legacy, legacy_reason = ledger.can_send("legacy_trigger")
    assert not allowed_legacy and legacy_reason == "unanswered_cap"
