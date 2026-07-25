"""
tests/test_profile_location_fallback.py — 2026-07-25，茶茶反馈

背景：用户反馈"我说我现在在绍兴，地点依然不会更改，天气也一直默认查杭州"。
根因有两处，均已在本次修复：

1. core/memory/user_profile.py::update() 的 pending-override 反抖动机制默认要求
   同一新值被"连续 2 次一致提取"才落盘覆盖；但 location 属于"此刻状态"，用户通常
   只提一次就不会再重复，导致 pending 永远停在 count=1，location 从此追不上现实
   （见 tests/test_user_profile_override.py 里新增的 8/8b 用例，覆盖机制本身）。
2. main.py 里 `_profile.get("location", "杭州")` 是经典 dict.get(key, default) 误用：
   default 只在 key 缺失时生效，但 user_profile 的默认 schema 里 "location" 这个 key
   永远存在（未设置时值是 None，不是缺失）。所以这一行从未真正触发过"杭州"兜底，
   location 为 None 时会把 None 传进 core/tool_dispatcher.py::get_probe_prompt()，
   而 location 一旦被第一次成功提取到某个值（例如"杭州"）,又会被上面第 1 点的反抖动
   卡死在那个值上——两个问题合起来正好复现"天气一直查杭州"的症状：不是真的兜底成杭州，
   是 location 字段本身卡死在了很早以前提取到的杭州。

本文件只覆盖第 2 点（.get 写法本身的行为差异）；第 1 点的机制回归见
tests/test_user_profile_override.py。
"""
from __future__ import annotations

import inspect


def test_dict_get_with_default_does_not_fall_back_on_none_value():
    """记录这个 dict.get() 语义坑本身，防止以后有人在类似地方写回旧写法。"""
    profile_with_key_but_none_value = {"location": None}  # 模拟从未设置过地点的画像
    assert profile_with_key_but_none_value.get("location", "杭州") is None, (
        "dict.get(key, default) 只在 key 缺失时才回落 default，"
        "key 存在但值为 None 时仍返回 None——这正是旧代码的 bug"
    )
    assert (profile_with_key_but_none_value.get("location") or "杭州") == "杭州", (
        "正确写法：or 才是真正的『值为空则回落默认值』"
    )


def test_main_py_uses_or_fallback_not_get_default_for_location():
    """静态回归：main.py 不应再出现 `.get("location", "杭州")` 这种旧写法。"""
    import main as _main

    src = inspect.getsource(_main)
    assert '_profile.get("location", "杭州")' not in src, (
        "main.py 不应再用 dict.get(key, default) 给 location 兜底"
        "（该写法在 location 已存在但为 None 时不生效，见本文件顶部说明）"
    )
    assert '_profile.get("location") or "杭州"' in src, (
        "main.py 应使用 profile.get('location') or '杭州' 的写法"
    )
