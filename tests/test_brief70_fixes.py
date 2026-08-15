from tests.fixtures.public_assets import TEST_CHAR_ID
import json
import random

import pytest


def _spend_config(provider):
    return {
        "spend": {
            "enabled": True,
            "daily_cap": 100,
            "monthly_cap": 100,
            "payee_whitelist": ["deepseek"],
            "balance_providers": [provider],
        }
    }


@pytest.mark.asyncio
async def test_spend_recovery_confirms_each_mandate_once(sandbox, monkeypatch):
    from core.actions import spend_ledger
    from core.scheduler.triggers import spend_monitor

    provider = {"name": "deepseek", "threshold": 10, "topup_amount": 20}
    monkeypatch.setattr("core.config_loader.get_config", lambda: _spend_config(provider))
    proposed = spend_ledger.append(action="api_topup", payee="deepseek", amount=20, status="proposed", origin="scheduler")
    spend_ledger.append(action="api_topup", payee="deepseek", amount=20, status="notified", origin="scheduler", mandate_id=proposed["mandate_id"])
    monkeypatch.setattr(spend_monitor.api_balance, "fetch_balance", lambda _: _async(30))
    monkeypatch.setattr("core.scheduler.loop._is_ready", lambda _: True)
    monkeypatch.setattr("core.scheduler.loop._mark", lambda _: None)
    monkeypatch.setattr("core.scheduler.loop._owner_id", lambda: "owner")

    for _ in range(3):
        await spend_monitor._check_spend_monitor()

    rows = spend_ledger.read_ledger()
    confirmed = [row for row in rows if row["status"] == "confirmed"]
    assert len(confirmed) == 1
    assert confirmed[0]["mandate_id"] == proposed["mandate_id"]
    assert spend_ledger.budget_usage()["daily_used"] == 20


def test_new_interest_keeps_baseline_selection_weight():
    from core.scheduler.triggers.practice import select_interest

    interests = [{"id": "new"}, {"id": "old", "learning_progress": 0.5}]
    rng = random.Random(20260712)
    hits = sum(select_interest(interests, rng)["id"] == "new" for _ in range(10_000))
    assert 0.12 <= hits / 10_000 <= 0.17


def test_note_replacement_allows_similar_revision_but_plain_dedup_remains(sandbox, monkeypatch):
    from core.growth import notes

    monkeypatch.setattr("core.memory.provenance_log.append", lambda *args, **kwargs: None)
    for text in ("我发现结尾要留具体物件", "我发现开头要具体", "我发现节奏要收住"):
        assert notes.apply_note("interest", text, source="test", char_id="c")
    revised = "我发现节奏要收住一点"
    assert notes.apply_note("interest", revised, source="test", replaces=3, char_id="c")
    assert notes.load("interest", char_id="c")[2]["text"] == revised
    assert not notes.apply_note("interest", "我发现节奏要收住一点点", source="test", char_id="c")


@pytest.mark.asyncio
async def test_stage_phase_b_does_not_echo_cut_against_owner(sandbox, monkeypatch):
    from core.stage.models import StageSettings
    from core.stage.runner import run_owner_turn
    from core.stage.store import create_stage

    candidate = type("Candidate", (), {"char_id": TEST_CHAR_ID, "total": 1.0, "parts": {}})()
    monkeypatch.setattr("core.stage.runner._rank_candidates", lambda *args, **kwargs: [candidate])

    create_stage("brief70-stage", "owner", [TEST_CHAR_ID], settings=StageSettings(min_responders=0, max_responders=0, max_ai_chain_depth=1))

    async def generate(_stage, _speaker, _transcript, _turn_id, _triggered_by):
        return "请认真看看这句话"

    result = await run_owner_turn("brief70-stage", "请认真看看这句话", generate_reply=generate)
    assert len(result.replies) == 1


@pytest.mark.asyncio
async def test_practice_trace_echoes_only_fact_not_work_body(sandbox, monkeypatch):
    from core.growth import practice_session as ps

    interest = {"id": "i", "name": "写诗", "domain": "writing", "level": 1, "status": "active", "recent_scores": [], "learning_progress": 0}
    monkeypatch.setattr("core.growth.interest_state.active_interests", lambda _: [interest])
    monkeypatch.setattr("core.character_loader.load", lambda _: type("C", (), {"name": "角色", "personality": "克制"})())
    monkeypatch.setattr("core.growth.interest_state.record_score", lambda *args, **kwargs: _async({**interest, "recent_scores": [6.5]}))
    replies = iter(["作品正文绝不能进日记", json.dumps({"score": 6.5, "strengths": ["具体"], "one_improvement": "收紧节奏"}, ensure_ascii=False), '{"note":null}'])
    monkeypatch.setattr("core.llm_client.chat", lambda *args, **kwargs: _async(next(replies)))
    traces = []
    monkeypatch.setattr("core.memory.action_trace.record", lambda *args, **kwargs: traces.append(kwargs))

    assert await ps.run_session({"uid": "owner", "char_id": "c", "interest_id": "i"})
    assert traces[0]["echo_event_log"] is True
    assert "作品正文绝不能进日记" not in traces[0]["result_digest"]


def test_interest_candidates_use_ranked_domains_and_human_names(monkeypatch):
    from core.scheduler.triggers.interest_seed import collect_candidates

    monkeypatch.setattr("core.memory.event_log.get_recent_days", lambda *args, **kwargs: "画画画画画歌")
    monkeypatch.setattr("core.memory.user_profile.load", lambda *args, **kwargs: {
        "important_facts": [{"text": "用户喜欢某个游戏，希望一起体验", "tag": "pref.media"}],
    })
    candidates = collect_candidates("owner", "c")
    topical = [item for item in candidates if item["origin"] == "topic_stats"]
    assert topical[0]["domain"] == "drawing"
    assert topical[0]["name"] != "画"
    assert all(item["origin"] != "user_pref_mirror" for item in candidates)


@pytest.mark.asyncio
async def test_visual_first_frame_is_not_put_on_cooldown(sandbox, monkeypatch):
    import admin.routers.perception as perception

    perception._last_accepted.clear()
    monkeypatch.setattr("core.config_loader.get_config", lambda: {"visual_perception": {"enabled": True}})
    monkeypatch.setattr(perception.time, "monotonic", lambda: 1.0)
    tasks = []
    def create_task(coro):
        tasks.append(coro)
        coro.close()
    monkeypatch.setattr(perception.asyncio, "create_task", create_task)
    class Upload:
        async def read(self): return b"image"

    result = await perception.ingest_visual(Upload(), "screen", True)
    assert result["processing"] is True and len(tasks) == 1


async def _async(value):
    return value
