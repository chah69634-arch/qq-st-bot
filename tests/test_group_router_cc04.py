"""
tests/test_group_router_cc04.py — CC-04 group management: delete / roster patch / group_defaults

Covers:
  - delete_stage() store function: returns True on success, False when not found
  - HTTP: DELETE /group/{id} (200 + 404 + auth)
  - HTTP: PATCH /group/{id}/roster (200 + 422 empty/dupes/unknown char + clamps max_responders)
  - settings_from_config(): reads group_defaults first, falls back to group_chat
"""

from __future__ import annotations
from tests.fixtures.public_assets import TEST_CHAR_ID, TEST_THIRD_CHAR_ID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

VALID_TOKEN = "cc04-test-secret"

_app = FastAPI()

from admin.routers.group import router as _group_router

_app.include_router(_group_router, prefix="/group")


@pytest.fixture(autouse=True)
def _patch_secret(monkeypatch):
    monkeypatch.setattr("admin.auth.get_admin_secret", lambda: VALID_TOKEN)


@pytest.fixture()
def client(sandbox):
    return TestClient(_app, raise_server_exceptions=True)


def _auth():
    return {"Authorization": f"Bearer {VALID_TOKEN}"}


def _stage(sandbox, group_id="grp-cc04", roster=(TEST_CHAR_ID,)):
    from core.stage.store import create_stage
    return create_stage(group_id, "owner", list(roster))


# ── delete_stage store unit ───────────────────────────────────────────────────

def test_delete_stage_returns_true_on_success(sandbox):
    from core.stage.store import create_stage, delete_stage
    create_stage("grp-del-1", "owner", [TEST_CHAR_ID])
    assert delete_stage("grp-del-1") is True


def test_delete_stage_removes_meta_file(sandbox):
    from core.sandbox import get_paths
    from core.stage.store import create_stage, delete_stage
    create_stage("grp-del-2", "owner", [TEST_CHAR_ID])
    delete_stage("grp-del-2")
    assert not get_paths().stage_meta(group_id="grp-del-2").exists()


def test_delete_stage_removes_transcript_file(sandbox):
    from core.sandbox import get_paths
    from core.stage.store import create_stage, delete_stage
    create_stage("grp-del-3", "owner", [TEST_CHAR_ID])
    delete_stage("grp-del-3")
    assert not get_paths().stage_transcript(group_id="grp-del-3").exists()


def test_delete_stage_returns_false_when_not_found(sandbox):
    from core.stage.store import delete_stage
    assert delete_stage("nonexistent-group") is False


def test_delete_stage_makes_load_stage_return_none(sandbox):
    from core.stage.store import create_stage, delete_stage, load_stage
    create_stage("grp-del-4", "owner", [TEST_CHAR_ID])
    delete_stage("grp-del-4")
    assert load_stage("grp-del-4") is None


def test_delete_stage_idempotent_second_call_returns_false(sandbox):
    from core.stage.store import create_stage, delete_stage
    create_stage("grp-del-5", "owner", [TEST_CHAR_ID])
    assert delete_stage("grp-del-5") is True
    assert delete_stage("grp-del-5") is False


# ── DELETE /group/{id} HTTP ───────────────────────────────────────────────────

def test_delete_group_200(client, sandbox):
    _stage(sandbox, "grp-http-del-1")
    r = client.delete("/group/grp-http-del-1", headers=_auth())
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["deleted"] == "grp-http-del-1"


def test_delete_group_404_for_nonexistent(client, sandbox):
    r = client.delete("/group/no-such-group", headers=_auth())
    assert r.status_code == 404


def test_delete_group_not_found_in_list_after_deletion(client, sandbox):
    _stage(sandbox, "grp-http-del-2")
    client.delete("/group/grp-http-del-2", headers=_auth())
    r = client.get("/group/list", headers=_auth())
    ids = [item["group_id"] for item in r.json()]
    assert "grp-http-del-2" not in ids


def test_delete_group_requires_auth(client, sandbox):
    _stage(sandbox, "grp-http-del-noauth")
    r = client.delete("/group/grp-http-del-noauth")
    assert r.status_code in (401, 403)


# ── PATCH /group/{id}/roster ──────────────────────────────────────────────────

def test_patch_roster_updates_members(client, sandbox):
    _stage(sandbox, "grp-roster-1", roster=(TEST_CHAR_ID,))
    r = client.patch(
        "/group/grp-roster-1/roster",
        json={"roster": [TEST_CHAR_ID, TEST_THIRD_CHAR_ID]},
        headers=_auth(),
    )
    assert r.status_code == 200
    data = r.json()
    char_ids = [m["char_id"] for m in data["roster"]]
    assert set(char_ids) == {TEST_CHAR_ID, TEST_THIRD_CHAR_ID}


def test_patch_roster_returns_summary_and_settings(client, sandbox):
    _stage(sandbox, "grp-roster-shape")
    r = client.patch(
        "/group/grp-roster-shape/roster",
        json={"roster": [TEST_CHAR_ID]},
        headers=_auth(),
    )
    assert r.status_code == 200
    data = r.json()
    assert "group_id" in data
    assert "settings" in data
    assert "roster" in data


def test_patch_roster_empty_roster_422(client, sandbox):
    _stage(sandbox, "grp-roster-empty")
    r = client.patch(
        "/group/grp-roster-empty/roster",
        json={"roster": []},
        headers=_auth(),
    )
    assert r.status_code == 422


def test_patch_roster_duplicate_members_422(client, sandbox):
    _stage(sandbox, "grp-roster-dup")
    r = client.patch(
        "/group/grp-roster-dup/roster",
        json={"roster": [TEST_CHAR_ID, TEST_CHAR_ID]},
        headers=_auth(),
    )
    assert r.status_code == 422


def test_patch_roster_unknown_char_422(client, sandbox):
    _stage(sandbox, "grp-roster-ghost")
    r = client.patch(
        "/group/grp-roster-ghost/roster",
        json={"roster": ["nonexistent-char-xyz"]},
        headers=_auth(),
    )
    assert r.status_code == 422


def test_patch_roster_404_for_nonexistent_group(client, sandbox):
    r = client.patch(
        "/group/no-such/roster",
        json={"roster": [TEST_CHAR_ID]},
        headers=_auth(),
    )
    assert r.status_code == 404


def test_patch_roster_clamps_max_responders(client, sandbox):
    """When shrinking roster below max_responders, max is clamped to new roster size."""
    from core.stage.models import StageSettings
    from core.stage.store import create_stage

    # Create group with max_responders=2 but only 1 char after patch
    settings = StageSettings(min_responders=1, max_responders=2)
    from core.stage.store import save_stage
    from dataclasses import replace
    stage = create_stage("grp-roster-clamp", "owner", [TEST_CHAR_ID, TEST_THIRD_CHAR_ID])
    # set max_responders=2
    from core.stage.models import now_iso
    stage2 = replace(stage, settings=StageSettings(min_responders=1, max_responders=2))
    save_stage(stage2)

    r = client.patch(
        "/group/grp-roster-clamp/roster",
        json={"roster": [TEST_CHAR_ID]},
        headers=_auth(),
    )
    assert r.status_code == 200
    data = r.json()
    assert data["settings"]["max_responders"] == 1


def test_patch_roster_requires_auth(client, sandbox):
    _stage(sandbox, "grp-roster-noauth")
    r = client.patch(
        "/group/grp-roster-noauth/roster",
        json={"roster": [TEST_CHAR_ID]},
    )
    assert r.status_code in (401, 403)


# ── settings_from_config group_defaults ──────────────────────────────────────

def test_settings_from_config_reads_group_defaults(monkeypatch):
    from core.stage.models import settings_from_config

    monkeypatch.setattr(
        "core.config_loader.get_config",
        lambda: {"group_defaults": {"min_responders": 2, "max_responders": 4}},
    )
    s = settings_from_config()
    assert s.min_responders == 2
    assert s.max_responders == 4


def test_settings_from_config_falls_back_to_group_chat(monkeypatch):
    from core.stage.models import settings_from_config

    monkeypatch.setattr(
        "core.config_loader.get_config",
        lambda: {"group_chat": {"min_responders": 3, "max_responders": 3}},
    )
    s = settings_from_config()
    assert s.min_responders == 3


def test_settings_from_config_group_defaults_beats_group_chat(monkeypatch):
    from core.stage.models import settings_from_config

    monkeypatch.setattr(
        "core.config_loader.get_config",
        lambda: {
            "group_defaults": {"min_responders": 2, "max_responders": 5},
            "group_chat": {"min_responders": 99, "max_responders": 99},
        },
    )
    s = settings_from_config()
    assert s.min_responders == 2
    assert s.max_responders == 5


def test_settings_from_config_empty_config_gives_defaults(monkeypatch):
    from core.stage.models import settings_from_config, StageSettings

    monkeypatch.setattr("core.config_loader.get_config", lambda: {})
    s = settings_from_config()
    assert s == StageSettings()
