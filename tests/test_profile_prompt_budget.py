"""Read-side safeguards for the bounded layer-5 profile projection."""
from __future__ import annotations

import time


def test_core_is_bounded_and_legacy_facts_are_archival():
    from core.memory.user_profile import PROFILE_CORE_MAX_CHARS, select_for_prompt

    profile = {
        "name": "A" * 200,
        "location": "B" * 200,
        "occupation": "C" * 200,
        "pets": "D" * 200,
        "interests": "这是一项偏好，不是每轮 identity core",
        "important_facts": [
            {"text": "这是一条旧 stable 长叙述", "tag": "stable", "ts": 0},
            "这是一条 legacy misc 长叙述",
        ],
    }

    selected = select_for_prompt(profile)

    assert len(selected["core_text"]) <= PROFILE_CORE_MAX_CHARS
    assert "旧 stable 长叙述" not in selected["core_text"]
    assert "legacy misc 长叙述" not in selected["core_text"]
    assert "偏好，不是每轮" not in selected["core_text"]
    assert selected["core_provenance"]["archived_fact_count"] == 2
    assert selected["core_provenance"]["archived_scalar_fields"] == ["interests"]


def test_preference_projection_is_bounded_and_prioritizes_tagged_results():
    from core.memory.user_profile import (
        PROFILE_PREF_MAX_CHARS,
        PROFILE_PREF_MAX_FACTS,
        select_for_prompt,
    )

    now = time.time()
    facts = [
        {"text": f"音乐偏好 {i} " + "x" * 100, "tag": "pref.music", "ts": now - i}
        for i in range(10)
    ]
    selected = select_for_prompt({"important_facts": facts}, {"topic.music"}, now=now)
    pref = selected["pref_text"]

    assert len(pref) <= PROFILE_PREF_MAX_CHARS
    assert pref.count("\n- ") <= PROFILE_PREF_MAX_FACTS
    assert selected["pref_provenance"]["tagged_count"] <= PROFILE_PREF_MAX_FACTS
    assert selected["pref_provenance"]["budget_excluded_count"] > 0


def test_sensitive_profile_content_is_stored_but_never_selected_for_prompt():
    from core.memory.user_profile import select_for_prompt

    profile = {
        "name": "小北",
        "important_facts": [
            {"text": "有明确的性偏好描述", "tag": "pref.media", "ts": time.time()},
            {"text": "喜欢看科幻电影", "tag": "pref.media", "ts": time.time()},
            {"text": "一段性偏好历史描述", "tag": "stable", "ts": 0},
        ],
    }

    selected = select_for_prompt(profile, {"topic.media"})

    assert "性偏好" not in selected["core_text"]
    assert "性偏好" not in selected["pref_text"]
    assert "喜欢看科幻电影" in selected["pref_text"]
    assert selected["pref_provenance"]["sensitive_blocked_count"] == 2
    assert selected["core_provenance"]["archived_fact_count"] == 1


def test_prompt_capture_preserves_budget_metadata_and_explicit_units():
    from core.observe import prompt_capture

    uid = "profile-budget-capture"
    prompt_capture.capture(
        uid,
        [{
            "role": "system",
            "content": "核心资料",
            "_layer": "5_profile",
            "_estimated_tokens": 2.4,
            "_budget_chars": 360,
            "_provenance": {
                "mode": "budgeted_whitelist",
                "selected_fields": ["name"],
                "archived_fact_count": 12,
            },
        }],
        {"token_estimate": 4, "char_estimate": 4, "estimated_tokens": 2.4},
    )

    snap = prompt_capture.get_snapshots(uid)[-1]
    layer = snap["layers"][0]
    assert snap["char_estimate"] == 4
    assert snap["estimated_tokens"] == 2.4
    assert layer["budget_chars"] == 360
    assert layer["est_tokens"] == 2.4
    assert layer["provenance"]["archived_fact_count"] == 12
