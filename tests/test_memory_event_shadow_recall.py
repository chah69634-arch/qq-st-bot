from __future__ import annotations

import asyncio
import json
import threading
import time

from tests.fixtures.public_assets import TEST_CHAR_ID, TEST_PEER_CHAR_ID


def _scope(uid: str, char_id: str = TEST_CHAR_ID):
    from core.memory.scope import MemoryScope

    return MemoryScope.reality_scope(uid, char_id)


def _seed(uid: str, char_id: str = TEST_CHAR_ID) -> None:
    from core.memory.event_store import append_event

    scope = _scope(uid, char_id)
    for seq in range(4):
        assert append_event(scope, {
            "event_id": f"shadow-event-{seq}",
            "turn_id": f"shadow-turn-{seq}",
            "seq": seq,
            "occurred_at": 1_700_100_000 + seq,
            "realm": "reality",
            "kind": "owner_chat",
            "actor": "user",
            "channel": "desktop",
            "source": "fixture",
            "visible_text": f"shadow evidence about topic {seq}",
            "memory_text": f"shadow evidence about topic {seq}",
        }).inserted


def test_shadow_recall_is_disabled_without_rollout(sandbox):
    from core.memory.event_shadow_recall import run_shadow_recall

    _seed("shadow-disabled")
    result = asyncio.run(run_shadow_recall(_scope("shadow-disabled"), "topic"))
    assert result["enabled"] is False
    assert result["status"] == "disabled"
    assert result["seed_event_ids"] == []


def test_shadow_recall_collects_scoped_ids_and_metrics(sandbox):
    from core.memory.event_shadow_recall import run_shadow_recall

    _seed("shadow-enabled")
    result = asyncio.run(run_shadow_recall(
        _scope("shadow-enabled"),
        "topic",
        old_ids=["shadow-event-2", "legacy-id"],
        old_chars=800,
        settings={
            "enabled": True,
            "seed_limit": 2,
            "window_before": 1,
            "window_after": 1,
            "max_related_per_seed": 0,
            "timeout_ms": 300,
            "max_trace_ids": 8,
        },
    ))
    assert result["status"] == "ok"
    assert result["seed_event_ids"] == ["shadow-event-3", "shadow-event-2"]
    assert "shadow-event-2" in result["new_event_ids"]
    assert result["candidate_count"] >= 2
    assert result["chars"] > 0
    assert result["tokens"] == (result["chars"] + 3) // 4
    assert result["old_chars"] == 800
    assert result["overlap_rate"] > 0
    assert result["event_overlap_rate"] == result["overlap_rate"]
    assert result["comparison_mode"] == "event_id_and_turn_id"
    assert result["old_unmapped_count"] == 0
    assert result["turn_overlap_rate"] == 0.0
    assert result["scope_rejections"] == 0
    assert result["sqlite_timeout_ms"] < result["timeout_ms"]
    assert "evidence about topic" not in json.dumps({k: result[k] for k in result if k.endswith("ids")})


def test_shadow_recall_allowlist_can_enable_one_character(sandbox):
    from core.memory.event_shadow_recall import enabled_for, run_shadow_recall

    _seed("shadow-allowlist")
    cfg = {"enabled": False, "uids": [], "char_ids": [TEST_CHAR_ID], "timeout_ms": 300}
    assert enabled_for("shadow-allowlist", TEST_CHAR_ID, cfg) is True
    assert enabled_for("shadow-allowlist", TEST_PEER_CHAR_ID, cfg) is False
    result = asyncio.run(run_shadow_recall(_scope("shadow-allowlist"), "topic", settings=cfg))
    assert result["enabled"] is True


def test_shadow_recall_timeout_is_fail_open(monkeypatch, sandbox):
    from core.memory import event_shadow_recall

    def slow(*_args, **_kwargs):
        time.sleep(0.2)
        return {}

    monkeypatch.setattr(event_shadow_recall, "_run_sync", slow)
    result = asyncio.run(event_shadow_recall.run_shadow_recall(
        _scope("shadow-timeout"), "topic", settings={"enabled": True, "timeout_ms": 20}
    ))
    assert result["status"] == "timeout"
    assert result["timeout_reason"] == "budget_exceeded"
    assert result["new_event_ids"] == []


def test_shadow_observability_and_settings_routes_are_exposed():
    from admin.admin_server import app
    from admin.routers.settings_feature_flags import FLAGS

    paths = app.openapi()["paths"]
    assert "/observability/memory-event-shadow-recall" in paths
    assert "/settings/event-shadow-recall" in paths
    assert "event_shadow_recall" in FLAGS


def test_shadow_rollout_settings_are_hot_reloaded(tmp_path, monkeypatch):
    import yaml
    from admin.routers import settings_feature_flags as flags
    from core import config_loader

    path = tmp_path / "config.yaml"
    path.write_text("event_shadow_recall:\n  enabled: false\n", encoding="utf-8")
    monkeypatch.setattr(flags, "CONFIG_FILE", path)
    monkeypatch.setattr(flags, "get_config", lambda: yaml.safe_load(path.read_text(encoding="utf-8")))
    monkeypatch.setattr(config_loader, "reload_config", lambda: None)

    result = asyncio.run(flags.update_event_shadow_recall_settings(
        flags.EventShadowRecallUpdate(enabled=False, uids=["one", "one"], char_ids=[TEST_CHAR_ID]), auth=None,
    ))
    assert result == {
        "enabled": False, "desired_enabled": False, "uids": ["one"],
        "char_ids": [TEST_CHAR_ID], "apply_mode": "hot_reload",
        "effective_state": "allowlist-active", "reload_status": "reloaded",
    }
    saved = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert saved["event_shadow_recall"]["char_ids"] == [TEST_CHAR_ID]


def test_shadow_trace_observability_omits_query_text(sandbox):
    from admin.routers.observability import memory_event_shadow_recall
    from core.recall_trace import write_trace

    uid = "shadow-observe"
    write_trace(uid, TEST_CHAR_ID, {
        "query": "private query must not be projected",
        "event_shadow_recall": {
            "enabled": True, "status": "ok", "seed_event_ids": ["shadow-event-1"],
            "new_event_ids": ["shadow-event-1", "shadow-event-2"], "expand_count": 1,
            "related_count": 0, "candidate_count": 2, "chars": 30, "tokens": 8,
            "old_chars": 20, "old_tokens": 5, "overlap_rate": 0.25,
            "scope_rejections": 0, "truncation_reason": "", "timeout_reason": "",
            "elapsed_ms": 1,
            "timeout_ms": 120, "sqlite_timeout_ms": 40,
        },
    })
    result = asyncio.run(memory_event_shadow_recall(uid, TEST_CHAR_ID, _auth=None))
    assert result["status_counts"] == {"ok": 1}
    assert "new_event_ids" not in result["records"][0]
    assert "seed_event_ids" not in result["records"][0]
    assert result["records"][0]["sqlite_timeout_ms"] == 40
    assert result["has_run"] is True
    assert result["summary"]["calls"] == 1
    assert "private query must not be projected" not in str(result)
    assert "query" not in result["records"][0]


def test_shadow_observability_empty_scope_and_auth_are_explicit(sandbox, monkeypatch):
    from fastapi.testclient import TestClient
    from admin.admin_server import app

    secret = "shadow-observability-state-read"
    monkeypatch.setattr("admin.auth.get_admin_secret", lambda: secret)
    client = TestClient(app, raise_server_exceptions=False)
    params = {"uid": "shadow-never-ran", "char_id": TEST_CHAR_ID}
    assert client.get("/observability/memory-event-shadow-recall", params=params).status_code == 401
    response = client.get(
        "/observability/memory-event-shadow-recall", params=params,
        headers={"Authorization": f"Bearer {secret}"},
    )
    assert response.status_code == 200
    result = response.json()
    assert result["has_run"] is False
    assert result["latest_date"] == ""
    assert "records" in result and result["records"] == []
    assert "event_id" not in response.text and "query" not in response.text


def test_shadow_recall_does_not_add_a_prompt_parameter():
    import inspect
    from core.prompt_builder import build

    assert "event_shadow_recall" not in inspect.signature(build).parameters


def test_shadow_comparison_maps_source_events_and_turns_but_not_episodic_ids(sandbox):
    from core.memory.event_shadow_recall import compare_legacy_results
    from core.memory.event_store import append_event

    scope = _scope("shadow-mapping")
    for event_id, actor in (("event-user", "user"), ("event-assistant", "assistant")):
        assert append_event(scope, {
            "event_id": event_id, "turn_id": "turn-shared", "occurred_at": 1,
            "realm": "reality", "kind": "owner_chat", "actor": actor,
        }).ok
    result = {
        "new_event_ids": ["event-user", "event-assistant", "event-extra"],
        "new_turn_ids": ["turn-shared", "turn-extra"],
        "new_event_turns": {
            "event-user": "turn-shared",
            "event-assistant": "turn-shared",
            "event-extra": "turn-extra",
        },
    }
    compared = compare_legacy_results(result, [
        {"source_event_ids": ["event-user"], "scope": {"uid": scope.uid, "char_id": TEST_CHAR_ID, "realm": "reality"}},
        {"turn_id": "turn-shared"},
        {"id": "episodic-opaque-id"},
        {"turn_id": "other-turn", "scope": {"uid": "other", "char_id": TEST_CHAR_ID, "realm": "reality"}},
    ], scope=scope)
    assert compared["old_result_count"] == 4
    assert compared["old_mapped_count"] == 2
    assert compared["old_unmapped_count"] == 2
    assert compared["old_mapped_event_count"] == 2
    assert compared["event_overlap_count"] == 2
    assert compared["turn_overlap_count"] == 1
    assert compared["omitted_event_count"] == 0
    assert compared["extra_event_count"] == 1
    assert compared["event_coverage"] == 1.0
    assert compared["comparison_scope_rejections"] == 1


def test_shadow_turn_in_ledger_but_not_new_recall_is_mapped_and_omitted(sandbox):
    from core.memory.event_shadow_recall import compare_legacy_results
    from core.memory.event_store import append_event

    scope = _scope("shadow-omitted-turn")
    assert append_event(scope, {"event_id": "omitted:user", "turn_id": "omitted", "occurred_at": 1,
                                "realm": "reality", "kind": "owner_chat", "actor": "user"}).ok
    compared = compare_legacy_results({"new_event_ids": [], "new_turn_ids": [], "new_event_turns": {}},
                                      [{"turn_id": "omitted"}], scope=scope)
    assert compared["old_mapped_count"] == 1
    assert compared["omitted_event_count"] == 1


def test_shadow_runs_different_scopes_in_parallel(monkeypatch):
    from core.memory import event_shadow_recall

    barrier = threading.Barrier(2, timeout=1.0)

    def concurrent_search(*_args, **_kwargs):
        barrier.wait()
        return {"items": [], "next_cursor": "", "truncation_reason": ""}

    monkeypatch.setattr(event_shadow_recall.event_query, "search", concurrent_search)

    async def run_both():
        cfg = {"enabled": True, "timeout_ms": 300, "max_related_per_seed": 0}
        return await asyncio.gather(
            event_shadow_recall.run_shadow_query(_scope("shadow-parallel-a"), "topic", settings=cfg),
            event_shadow_recall.run_shadow_query(_scope("shadow-parallel-b"), "topic", settings=cfg),
        )

    results = asyncio.run(run_both())
    assert [result["status"] for result in results] == ["ok", "ok"]
