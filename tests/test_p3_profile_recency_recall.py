"""
tests/test_p3_profile_recency_recall.py — P3 验收

验收条件：
1. 旧 important_facts（纯 str）归一化兜底，读取侧视为 archival，不再常驻注入
2. pref.music（旧 ts=0）+ 近期 habit：平时只注入 habit；tag 命中时 pref.music 也被召回
3. 稳定字段（occupation/location）行为不变，始终出现在 5_profile 层
4. _normalize_fact / _is_recency_tag 行为正确
"""
from __future__ import annotations

import time

import pytest


# ─── _normalize_fact ──────────────────────────────────────────────────────────

def test_normalize_str_fact():
    from core.memory.user_profile import _normalize_fact

    result = _normalize_fact("喜欢游泳")
    assert result == {"text": "喜欢游泳", "tag": "misc", "ts": 0.0}


def test_normalize_dict_fact_passthrough():
    from core.memory.user_profile import _normalize_fact

    fact = {"text": "喜欢周杰伦", "tag": "pref.music", "ts": 1719360000}
    result = _normalize_fact(fact)
    assert result["text"] == "喜欢周杰伦"
    assert result["tag"] == "pref.music"
    assert result["ts"] == 1719360000.0


def test_normalize_dict_missing_fields():
    from core.memory.user_profile import _normalize_fact

    result = _normalize_fact({"text": "爱跑步"})
    assert result["tag"] == "misc"
    assert result["ts"] == 0.0


# ─── _is_recency_tag ─────────────────────────────────────────────────────────

def test_recency_tag_known_types():
    from core.memory.user_profile import _is_recency_tag

    for tag in ("pref.music", "pref.food", "pref.media", "habit", "health"):
        assert _is_recency_tag(tag), f"{tag!r} 应为 recency 门控"


def test_recency_tag_pref_prefix():
    from core.memory.user_profile import _is_recency_tag

    assert _is_recency_tag("pref.anime") is True
    assert _is_recency_tag("pref.sport") is True


def test_stable_tags_not_recency():
    from core.memory.user_profile import _is_recency_tag

    for tag in ("stable", "misc", ""):
        assert _is_recency_tag(tag) is False, f"{tag!r} 不应为 recency 门控"


# ─── prompt_builder 层 5 召回逻辑 ────────────────────────────────────────────

def _make_profile(**kwargs) -> dict:
    base = {
        "name": None,
        "location": None,
        "pets": None,
        "interests": None,
        "occupation": None,
        "important_facts": [],
    }
    base.update(kwargs)
    return base


def _build_layer5(profile: dict, tags: set[str]) -> tuple[list, list]:
    """Exercise the production layer-5 selector, not a copied implementation."""
    from core.memory.user_profile import select_for_prompt

    selection = select_for_prompt(profile, tags)
    profile_msgs = (
        [{"_layer": "5_profile", "content_parts": [selection["core_text"]]}]
        if selection["core_text"] else []
    )
    recalled = [
        line[2:] for line in selection["pref_text"].splitlines()
        if line.startswith("- ")
    ]
    pref_msgs = (
        [{
            "_layer": "5_profile_pref",
            "recalled": recalled,
            "tagged": ["selected"] * selection["pref_provenance"]["tagged_count"],
            "recency": ["selected"] * selection["pref_provenance"]["recency_count"],
        }]
        if selection["pref_text"] else []
    )
    return profile_msgs, pref_msgs


# ─── 验收 2：pref.music（旧ts）+ 近期 habit ──────────────────────────────────

class TestRecencyAndTagRecall:

    def _profile_with_music_and_habit(self) -> dict:
        now = time.time()
        return _make_profile(
            important_facts=[
                {"text": "喜欢听周杰伦", "tag": "pref.music", "ts": 0},   # 旧 ts
                {"text": "每天早上跑步", "tag": "habit", "ts": now - 3600},  # 近期
            ]
        )

    def test_only_recent_habit_injected_without_tag(self):
        """平时（无 music tag）：只注入近期 habit，不注入旧 pref.music"""
        profile = self._profile_with_music_and_habit()
        _, pref_msgs = _build_layer5(profile, tags=set())

        assert len(pref_msgs) == 1
        recalled = pref_msgs[0]["recalled"]
        assert "每天早上跑步" in recalled
        assert "喜欢听周杰伦" not in recalled

    def test_music_recalled_when_tag_hits(self):
        """用户问起音乐时 → pref.music 被召回，即使 ts 很旧"""
        profile = self._profile_with_music_and_habit()
        _, pref_msgs = _build_layer5(profile, tags={"music"})

        assert len(pref_msgs) == 1
        recalled = pref_msgs[0]["recalled"]
        assert "喜欢听周杰伦" in recalled

    def test_music_recalled_via_pref_tag_key(self):
        """pref.music tag 匹配：tag_key='music'，query tag 含 'music' 即命中"""
        profile = _make_profile(
            important_facts=[
                {"text": "最爱听古典乐", "tag": "pref.music", "ts": 0},
            ]
        )
        _, pref_msgs = _build_layer5(profile, tags={"music", "recommend"})
        assert pref_msgs and "最爱听古典乐" in pref_msgs[0]["recalled"]

    def test_provenance_mode_tagged_when_tag_hit(self):
        """tag 命中召回时，tagged_count > 0"""
        profile = self._profile_with_music_and_habit()
        _, pref_msgs = _build_layer5(profile, tags={"music"})
        assert pref_msgs[0]["tagged"]  # tagged 列表非空

    def test_provenance_mode_recency_only(self):
        """无 tag 命中时，tagged 列表为空，recency 列表非空"""
        profile = self._profile_with_music_and_habit()
        _, pref_msgs = _build_layer5(profile, tags=set())
        assert not pref_msgs[0]["tagged"]
        assert pref_msgs[0]["recency"]


# ─── 验收 1：旧 str 条目兼容 ─────────────────────────────────────────────────

class TestLegacyStrFacts:

    def test_old_str_fact_is_archival_not_ambient_context(self):
        """纯 str 条目归一化为 misc，但不再作为稳定段常驻注入。"""
        profile = _make_profile(important_facts=["喜欢画画", "养了一只猫"])
        profile_msgs, pref_msgs = _build_layer5(profile, tags=set())

        assert not profile_msgs
        assert not pref_msgs, "纯 misc 条目不应出现在偏好段"

    def test_mixed_str_and_dict_facts(self):
        """str 和 dict 混合：str 走稳定段，dict pref 走偏好段"""
        now = time.time()
        profile = _make_profile(
            important_facts=[
                "有一只柴犬",  # 旧 str → misc → 稳定段
                {"text": "喜欢看动漫", "tag": "pref.media", "ts": now - 3600},  # 近期
            ]
        )
        profile_msgs, pref_msgs = _build_layer5(profile, tags=set())
        assert not profile_msgs, "legacy misc 不得进入常驻 core"
        assert pref_msgs and "喜欢看动漫" in pref_msgs[0]["recalled"]


# ─── 验收 3：稳定字段始终注入 ────────────────────────────────────────────────

class TestStableFieldsAlwaysInjected:

    def test_occupation_always_in_profile(self):
        profile = _make_profile(occupation="大学生", location="杭州")
        profile_msgs, _ = _build_layer5(profile, tags=set())
        assert profile_msgs
        content = " ".join(profile_msgs[0]["content_parts"])
        assert "大学生" in content
        assert "杭州" in content

    def test_stable_tag_fact_is_archival(self):
        """tag=stable 的自由文本保留在档案中，但不再常驻注入。"""
        profile = _make_profile(
            important_facts=[{"text": "曾留学两年", "tag": "stable", "ts": 0}]
        )
        profile_msgs, pref_msgs = _build_layer5(profile, tags=set())
        assert not profile_msgs
        assert not pref_msgs

    def test_out_of_window_recency_fact_suppressed(self):
        """超出 90 天窗口且无 tag 命中的偏好事实不注入"""
        old_ts = time.time() - 100 * 86400  # 100 天前
        profile = _make_profile(
            important_facts=[
                {"text": "曾经喜欢过嘻哈", "tag": "pref.music", "ts": old_ts}
            ]
        )
        _, pref_msgs = _build_layer5(profile, tags=set())
        assert not pref_msgs, "90天外且无 tag 命中，不应注入"

    def test_out_of_window_fact_recalled_by_tag(self):
        """超出 90 天但当前 tag 命中 → 仍应召回"""
        old_ts = time.time() - 100 * 86400
        profile = _make_profile(
            important_facts=[
                {"text": "曾经喜欢过嘻哈", "tag": "pref.music", "ts": old_ts}
            ]
        )
        _, pref_msgs = _build_layer5(profile, tags={"music"})
        assert pref_msgs and "曾经喜欢过嘻哈" in pref_msgs[0]["recalled"]
