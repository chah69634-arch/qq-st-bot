from __future__ import annotations

import asyncio
import sqlite3
from types import SimpleNamespace

import pytest

from tests.fixtures.public_assets import TEST_CHAR_ID, TEST_PEER_CHAR_ID


def _scope(uid: str, char_id: str = TEST_CHAR_ID):
    from core.memory.scope import MemoryScope

    return MemoryScope.reality_scope(uid, char_id)


def _seed(uid: str, char_id: str = TEST_CHAR_ID) -> None:
    from core.memory.event_store import append_event

    scope = _scope(uid, char_id)
    for seq in range(3):
        assert append_event(scope, {
            "event_id": f"proposal-event-{seq}", "turn_id": f"proposal-turn-{seq}", "seq": seq,
            "occurred_at": 1_700_000_000 + seq, "realm": "reality", "kind": "owner_chat",
            "actor": "user", "channel": "desktop", "memory_text": f"event text {seq}",
        }).inserted


def test_proposals_are_scoped_deduplicated_and_separate_from_deterministic_edges(sandbox):
    from core.memory import event_store

    uid = "proposal-store-owner"
    _seed(uid)
    scope = _scope(uid)
    proposal = {
        "from_event_id": "proposal-event-0", "to_event_id": "proposal-event-1",
        "relation_type": "possible_cause", "reason": "A tentative relationship.", "confidence": 0.4,
        "model": "fixture-model", "preset": "fixture-preset", "model_version": "v1", "prompt_hash": "a" * 64,
    }
    assert event_store.append_edge_proposal(scope, proposal) is True
    assert event_store.append_edge_proposal(scope, proposal) is False
    with pytest.raises(ValueError, match="invalid_proposal_scope"):
        event_store.append_edge_proposal(scope, {**proposal, "to_event_id": "other-scope-event"})
    with pytest.raises(ValueError):
        event_store.append_edge_proposal(scope, {**proposal, "relation_type": "causes"})
    from core.memory.scope import MemoryScope
    with pytest.raises(ValueError):
        event_store.append_edge_proposal(
            MemoryScope.dream_scope(uid, TEST_CHAR_ID, "fixture-world"), proposal
        )

    path = event_store.resolve_path(scope, "event_store")
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM event_edge_proposals").fetchone()[0] == 1
        # The deterministic edge table is not a candidate-edge sink.
        assert connection.execute(
            "SELECT COUNT(*) FROM event_edges WHERE relation_type='possible_cause'"
        ).fetchone()[0] == 0

    assert event_store.recent_events_for_proposal(_scope(uid, TEST_PEER_CHAR_ID)) == []


def test_candidate_json_validation_rejects_cross_window_and_invalid_relations():
    from core.scheduler.triggers.event_edge_proposer import _parse_candidates

    ids = {"a", "b"}
    parsed = _parse_candidates(
        '[{"from_event_id":"a","to_event_id":"b","relation_type":"same_topic","reason":"same work","confidence":0.8}]',
        ids, 2,
    )
    assert parsed[0]["relation_type"] == "same_topic"
    with pytest.raises(ValueError):
        _parse_candidates('[{"from_event_id":"a","to_event_id":"outside","relation_type":"same_topic","reason":"x","confidence":0.5}]', ids, 2)
    with pytest.raises(ValueError):
        _parse_candidates('[{"from_event_id":"a","to_event_id":"b","relation_type":"causes","reason":"x","confidence":0.5}]', ids, 2)


def test_proposer_records_failures_budget_and_observability_without_memory_writes(sandbox, monkeypatch):
    from core import llm_client
    from core.memory import event_store
    from core.scheduler.triggers import event_edge_proposer as proposer

    uid = "proposal-trigger-owner"
    _seed(uid)
    cfg = {
        "enabled": True, "cooldown_seconds": 60, "event_window_size": 3,
        "max_candidates_per_run": 2, "max_daily_calls": 1,
        "max_daily_tokens": 64, "max_tokens_per_call": 64,
    }

    async def invalid_model(*_args, **_kwargs):
        return "not json"

    monkeypatch.setattr(llm_client, "chat", invalid_model)
    asyncio.run(proposer._propose_scope(uid, TEST_CHAR_ID, cfg))
    scope = _scope(uid)
    snap = event_store.edge_proposal_observability_snapshot(scope, day_key=proposer._day_key(), daily_call_limit=1, daily_token_limit=64)
    assert snap["runs"] == 1
    assert snap["failed_count"] == 1
    assert snap["candidate_count"] == 0
    assert snap["daily"]["calls"] == 1
    assert snap["daily"]["tokens"] == 64

    # Persisted daily accounting blocks a second call even after a process restart.
    asyncio.run(proposer._propose_scope(uid, TEST_CHAR_ID, {**cfg, "cooldown_seconds": 0}))
    assert event_store.edge_proposal_observability_snapshot(scope)["runs"] == 1

    from admin.routers.observability import memory_event_edge_proposals
    observed = asyncio.run(memory_event_edge_proposals(uid, TEST_CHAR_ID, _auth=None))
    assert observed["failed_count"] == 1
    assert observed["by_relation"] == {}
    assert observed["has_run"] is True
    assert "effective_state" in observed
    assert "route_effective" in observed
    assert "private" not in str(observed)


def test_proposal_observability_route_is_exposed():
    from admin.admin_server import app

    assert "/observability/memory-event-edge-proposals" in app.openapi()["paths"]


def test_scheduler_discovers_only_existing_healthy_sqlite3_ledgers(sandbox, monkeypatch):
    from core.memory.path_resolver import resolve_path
    from core.scheduler import loop
    from core.scheduler.triggers import event_edge_proposer as proposer

    uid = "proposal-discovery-owner"
    _seed(uid)
    missing_scope = _scope("proposal-discovery-missing")
    resolve_path(missing_scope, "event_store").parent.mkdir(parents=True)
    unhealthy_scope = _scope("proposal-discovery-unhealthy")
    unhealthy_path = resolve_path(unhealthy_scope, "event_store")
    unhealthy_path.parent.mkdir(parents=True)
    unhealthy_path.write_text("not a sqlite ledger", encoding="utf-8")
    calls: list[tuple[str, str]] = []

    async def fake_propose(found_uid, char_id, _cfg):
        calls.append((found_uid, char_id))

    monkeypatch.setattr(proposer, "_config", lambda: {
        "enabled": True, "scope_timeout_seconds": 1,
    })
    monkeypatch.setattr(proposer, "_propose_scope", fake_propose)
    monkeypatch.setattr(loop, "_is_ready", lambda _name: True)
    monkeypatch.setattr(loop, "_mark", lambda _name: None)
    monkeypatch.setattr(
        "core.asset_registry.get_registry",
        lambda: SimpleNamespace(list_all=lambda _kind: [SimpleNamespace(id=TEST_CHAR_ID)]),
    )

    asyncio.run(proposer._check_event_edge_proposer())
    assert calls == [(uid, TEST_CHAR_ID)]
    discovery = proposer.discovery_observability_snapshot()
    assert discovery["eligible_scopes"] >= 1
    assert discovery["missing_ledgers"] >= 1
    assert discovery["unhealthy_ledgers"] >= 1


def test_scheduler_scope_timeout_releases_discovery_loop(sandbox, monkeypatch):
    from core.scheduler import loop
    from core.scheduler.triggers import event_edge_proposer as proposer

    uid = "proposal-timeout-owner"
    _seed(uid)

    async def slow_propose(*_args):
        await asyncio.sleep(1)

    monkeypatch.setattr(proposer, "_config", lambda: {
        "enabled": True, "scope_timeout_seconds": 0.01,
    })
    monkeypatch.setattr(proposer, "_propose_scope", slow_propose)
    monkeypatch.setattr(loop, "_is_ready", lambda _name: True)
    monkeypatch.setattr(loop, "_mark", lambda _name: None)
    monkeypatch.setattr(
        "core.asset_registry.get_registry",
        lambda: SimpleNamespace(list_all=lambda _kind: [SimpleNamespace(id=TEST_CHAR_ID)]),
    )

    asyncio.run(proposer._check_event_edge_proposer())
    assert proposer.discovery_observability_snapshot()["timed_out_scopes"] >= 1


def test_proposer_filters_isolated_sources_before_text_projection_and_write(sandbox):
    from core.memory import event_store

    scope = _scope("proposal-source-policy")
    for event_id, source, occurred_at in (
        ("proposal-ordinary", "user_chat", 1),
        ("proposal-web", "web", 2),
        ("proposal-dream", "dream_echo", 3),
    ):
        assert event_store.append_event(scope, {
            "event_id": event_id, "turn_id": event_id, "occurred_at": occurred_at,
            "realm": "reality", "kind": "owner_chat", "actor": "user",
            "source": source, "memory_text": f"private {source} body",
        }).inserted

    projected = event_store.recent_events_for_proposal(scope, limit=3)
    assert [item["event_id"] for item in projected] == ["proposal-ordinary"]
    proposal = {
        "from_event_id": "proposal-ordinary", "to_event_id": "proposal-web",
        "relation_type": "same_topic", "reason": "must be rejected", "confidence": 0.5,
    }
    with pytest.raises(ValueError, match="invalid_proposal_source"):
        event_store.append_edge_proposal(scope, proposal)
    observed = event_store.edge_proposal_observability_snapshot(scope)
    assert observed["source_policy"]["input_count"] >= 3
    assert observed["source_policy"]["filtered_count"] >= 3
