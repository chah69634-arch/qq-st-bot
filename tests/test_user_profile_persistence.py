"""Profile persistence safety: atomic writes, scoped locking, and clear semantics."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor


def test_failed_atomic_write_keeps_previous_profile_parseable(sandbox, monkeypatch):
    from core.memory import user_profile

    uid = "profile_atomic_failure"
    user_profile.save(uid, {"name": "before", "external_state": {"v": 1}})
    path = sandbox.user_memory_root(uid, char_id=user_profile.DEFAULT_CHAR_ID) / "profile.json"
    before = path.read_text(encoding="utf-8")

    monkeypatch.setattr(user_profile, "safe_write_text", lambda *_args, **_kwargs: False, raising=False)
    # Patch the imported helper where _save resolves it, preserving the real file.
    import core.safe_write as safe_write
    monkeypatch.setattr(safe_write, "safe_write_text", lambda *_args, **_kwargs: False)

    assert user_profile._save(uid, {"name": "after"}) is False
    assert path.read_text(encoding="utf-8") == before
    assert json.loads(before)["name"] == "before"
    assert path.is_relative_to(sandbox._base)


def test_concurrent_mutations_preserve_distinct_fields(sandbox):
    from core.memory import user_profile

    uid = "profile_concurrent"
    user_profile.save(uid, {"external_state": "keep"})

    def set_name():
        user_profile.mutate(uid, lambda profile: profile.__setitem__("name", "Ada"))

    def set_location():
        user_profile.mutate(uid, lambda profile: profile.__setitem__("location", "Hangzhou"))

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda fn: fn(), (set_name, set_location)))

    profile = user_profile.load(uid)
    assert profile["name"] == "Ada"
    assert profile["location"] == "Hangzhou"
    assert profile["external_state"] == "keep"


def test_clear_only_removes_profile_owned_fields(sandbox):
    from core.memory import user_profile

    uid = "profile_clear"
    user_profile.save(uid, {
        "name": "Ada",
        "location": "Hangzhou",
        "pets": "cat",
        "interests": "music",
        "occupation": "engineer",
        "important_facts": [{"text": "fact", "tag": "misc", "ts": 1}],
        "_pending_overrides": {"location": {"new_value": "Ningbo", "count": 1}},
        "sleep_segments": [{"duration_minutes": 420}],
        "last_period_date": "2026-01-01",
        "heart_rate_events": [{"value": 80}],
        "affection": 123,
        "unknown_extension": {"preserve": True},
    })

    user_profile.clear(uid)
    profile = user_profile.load(uid)

    assert profile["name"] is None
    assert profile["location"] is None
    assert profile["pets"] is None
    assert profile["interests"] is None
    assert profile["occupation"] is None
    assert profile["important_facts"] == []
    assert "_pending_overrides" not in profile
    assert profile["sleep_segments"] == [{"duration_minutes": 420}]
    assert profile["last_period_date"] == "2026-01-01"
    assert profile["heart_rate_events"] == [{"value": 80}]
    assert profile["affection"] == 123
    assert profile["unknown_extension"] == {"preserve": True}
