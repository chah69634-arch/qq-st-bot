from __future__ import annotations
import time
import pytest

from core.growth import interest_state as state

def test_learning_progress_signs():
    assert state.learning_progress([1,2,3]) > 0
    assert state.learning_progress([2,2,2]) == 0
    assert state.learning_progress([3,2,1]) < 0
    assert state.learning_progress([1]) == 0

@pytest.mark.asyncio
async def test_add_limit_stall_and_lifecycle(sandbox, monkeypatch):
    monkeypatch.setattr("core.memory.provenance_log.append",lambda *a,**k:None)
    entries=[]
    for i in range(4): entries.append(await state.add_interest(f"兴趣{i}","writing","topic_stats",char_id="c",uid="u"))
    assert sum(x is not None for x in entries)==3
    item=entries[0]
    for score in [5,5,5,5]: updated=await state.record_score(item["id"],score,char_id="c",uid="u")
    assert updated["stalled_since"] is not None
    stalled=updated["stalled_since"]
    changes=await state.apply_lifecycle(char_id="c",uid="u",now=stalled+31*86400)
    assert changes[0][2]=="paused"
    changes=await state.apply_lifecycle(char_id="c",uid="u",now=stalled+121*86400)
    assert changes[0][2]=="retired"

@pytest.mark.asyncio
async def test_seed_disabled_is_noop(monkeypatch):
    monkeypatch.setattr("core.scheduler.triggers.interest_seed._config",lambda:{"enabled":False})
    from core.scheduler.triggers.interest_seed import _check_interest_seed
    await _check_interest_seed()


def test_legacy_user_preference_mirror_is_retired_on_read(sandbox):
    path = state._path("c")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        '{"interests":[{"id":"legacy-pref","name":"用户偏好原句","domain":"other",'
        '"origin":"user_pref_mirror","status":"active"}]}',
        encoding="utf-8",
    )

    loaded = state.load("c")["interests"]
    assert loaded[0]["origin"] == "user_pref_mirror"
    assert loaded[0]["status"] == "retired"
    assert state.active_interests("c") == []
