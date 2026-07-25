"""
tests/test_user_profile_override.py — FIX-10

验收（方案 A，N=2）：
1. 空字段首次仍能正常填入（旧逻辑不变）
2. 非空字段 + 相同新值喂 1 次 → 不覆盖，挂起 pending
3. 非空字段 + 相同新值连续 2 次 → 落盘覆盖
4. pending 候选值中途换新值 → 重置计数，不覆盖
5. important_facts 去重追加行为不变
6. 新旧值相同 → 不产生 pending，不写日志
"""
from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# 1. 空字段直接填入
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_empty_field_filled_directly(sandbox):
    from core.memory import user_profile as _up

    await _up.update("uid_empty", {"interests": "画画"})
    profile = _up.load("uid_empty")
    assert profile["interests"] == "画画"
    assert "_pending_overrides" not in profile


# ---------------------------------------------------------------------------
# 2. 非空字段 + 新值一次 → 不覆盖，挂起 pending
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_nonempty_field_single_new_value_not_overridden(sandbox):
    from core.memory import user_profile as _up

    _up.save("uid_once", {"interests": "跑步"})

    await _up.update("uid_once", {"interests": "画画"})
    profile = _up.load("uid_once")

    assert profile["interests"] == "跑步", "单次新值不应覆盖已有值"
    assert "_pending_overrides" in profile
    assert profile["_pending_overrides"]["interests"]["new_value"] == "画画"
    assert profile["_pending_overrides"]["interests"]["count"] == 1


# ---------------------------------------------------------------------------
# 3. 非空字段 + 相同新值连续 2 次 → 覆盖
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_nonempty_field_two_consistent_updates_overrides(sandbox):
    from core.memory import user_profile as _up

    _up.save("uid_twice", {"interests": "跑步"})

    await _up.update("uid_twice", {"interests": "画画"})
    await _up.update("uid_twice", {"interests": "画画"})

    profile = _up.load("uid_twice")
    assert profile["interests"] == "画画", "连续 2 次一致提取应覆盖旧值"
    assert "_pending_overrides" not in profile, "落盘后应清除 pending"


# ---------------------------------------------------------------------------
# 4. pending 候选值中途换新值 → 重置计数，不覆盖
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pending_value_reset_on_different_new_value(sandbox):
    from core.memory import user_profile as _up

    _up.save("uid_reset", {"interests": "跑步"})

    await _up.update("uid_reset", {"interests": "画画"})   # count=1，candidate=画画
    await _up.update("uid_reset", {"interests": "游泳"})   # 候选值变了 → 重置 count=1

    profile = _up.load("uid_reset")
    assert profile["interests"] == "跑步", "候选值中途变化，不应覆盖"
    assert profile["_pending_overrides"]["interests"]["new_value"] == "游泳"
    assert profile["_pending_overrides"]["interests"]["count"] == 1


# ---------------------------------------------------------------------------
# 5. important_facts 去重追加行为不变
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_important_facts_dedup_append_unchanged(sandbox):
    from core.memory import user_profile as _up

    _up.save("uid_facts", {"interests": "跑步", "important_facts": ["有猫"]})

    await _up.update("uid_facts", {"important_facts": ["有猫", "爱喝茶"]})
    profile = _up.load("uid_facts")

    # P3 后 important_facts 元素可能是 str（旧条目）或 dict（新条目），用 text 比较
    texts = [_up._normalize_fact(f)["text"] for f in profile["important_facts"]]
    assert "有猫" in texts
    assert "爱喝茶" in texts
    assert texts.count("有猫") == 1, "去重：已有条目不重复追加"


# ---------------------------------------------------------------------------
# 6. 新旧值相同 → 无 pending，无变化
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_same_value_no_pending(sandbox):
    from core.memory import user_profile as _up

    _up.save("uid_same", {"interests": "跑步"})

    await _up.update("uid_same", {"interests": "跑步"})
    profile = _up.load("uid_same")

    assert profile["interests"] == "跑步"
    assert "_pending_overrides" not in profile


# ---------------------------------------------------------------------------
# 7. 三次连续相同新值（N+1 次）仍只覆盖一次，落盘后清除 pending
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_override_applied_once_on_threshold_then_cleared(sandbox):
    from core.memory import user_profile as _up

    _up.save("uid_3x", {"interests": "跑步"})

    for _ in range(3):
        await _up.update("uid_3x", {"interests": "画画"})

    profile = _up.load("uid_3x")
    assert profile["interests"] == "画画"
    assert "_pending_overrides" not in profile


# ---------------------------------------------------------------------------
# 8. location 单独降阈值为 1（2026-07-25，茶茶反馈"说了在绍兴，地点始终不更新"）
#
# 默认阈值=2 要求两次"连续一致提取"，但 extract_and_update 只喂最近 10 条用户
# 发言——用户提一次新地点、话题很快岔开后就再也凑不出第二次，pending 永远停在
# count=1，location 从此追不上现实（连带天气工具一直查旧城市）。location 是
# "此刻状态"而非容易被幻觉污染的人设描述，理应单次生效；其余字段保持默认阈值
# 不变（下面 test 8b 验证 name 仍是旧行为，防止误伤）。
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_location_single_extraction_overrides_immediately(sandbox):
    from core.memory import user_profile as _up

    _up.save("uid_loc", {"location": "杭州"})

    await _up.update("uid_loc", {"location": "绍兴"})  # 只提一次，随后话题就岔开

    profile = _up.load("uid_loc")
    assert profile["location"] == "绍兴", "location 单次清晰提取应立即覆盖旧值，不应挂起等第二次"
    assert "_pending_overrides" not in profile


@pytest.mark.asyncio
async def test_name_still_requires_two_consistent_extractions(sandbox):
    """回归防误伤：只有 location 降阈值，name 等其余字段仍是默认 2 次连续阈值。"""
    from core.memory import user_profile as _up

    _up.save("uid_name", {"name": "小明"})

    await _up.update("uid_name", {"name": "小红"})
    profile = _up.load("uid_name")
    assert profile["name"] == "小明", "name 单次新值不应立即覆盖（默认阈值仍为 2）"
    assert profile["_pending_overrides"]["name"]["count"] == 1

    await _up.update("uid_name", {"name": "小红"})
    profile = _up.load("uid_name")
    assert profile["name"] == "小红", "name 连续 2 次一致提取后应覆盖"
    assert "_pending_overrides" not in profile
