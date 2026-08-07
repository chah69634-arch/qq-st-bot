from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from admin.auth import TokenInfo
from admin.routers.system import router as system_router
from admin.routers.users import router as users_router
from core.data_paths import DataPaths
from core.test_data_guard import classify_test_directories, is_test_identifier


@pytest.mark.parametrize(
    "value",
    [
        "uid_order_test",
        "uid_lock_scope_test",
        "uid_timeout_test",
        "pytest_unit",
        "test_session_gw0",
    ],
)
def test_high_confidence_test_identifiers_are_classified(value):
    assert is_test_identifier(value)


@pytest.mark.parametrize("value", ["owner", "1043484516", "testimony", "user_testimony"])
def test_normal_user_identifiers_are_not_classified(value):
    assert not is_test_identifier(value)


def test_production_runtime_rejects_test_uid_without_creating_path(tmp_path):
    paths = DataPaths(mode="production")
    paths._base = tmp_path / "data"

    with pytest.raises(RuntimeError, match="production runtime"):
        paths.user_memory_root("uid_order_test")
    assert not (paths._base / "runtime" / "memory").exists()


def test_production_runtime_rejects_test_session(tmp_path):
    paths = DataPaths(mode="production")
    paths._base = tmp_path / "data"

    with pytest.raises(RuntimeError, match="production runtime"):
        paths.activity_session_dir(
            char_id="character",
            uid="owner",
            activity_type="reading",
            session_id="test_session_gw0",
        )


def test_test_session_id_cannot_escape_test_sandbox():
    with pytest.raises(ValueError, match="unsafe user_id"):
        DataPaths(mode="test", test_session_id="../outside")


def test_explicit_installation_paths_are_anchored_without_changing_cwd(tmp_path):
    import core.sandbox as sandbox

    installation = tmp_path / "offline-installation"
    cwd_before = Path.cwd()
    singleton_before = sandbox._instance
    paths = sandbox.paths_for_installation(installation)

    assert paths.mode == "production"
    assert paths.root_dir() == installation.resolve() / "data"
    assert paths.layout_version() == installation.resolve() / "data" / "layout_version.json"
    assert paths.service_state() == installation.resolve() / "data" / "runtime" / "service_state.json"
    assert paths.userdata_root() == installation.resolve() / "userdata"
    assert Path.cwd() == cwd_before
    assert sandbox._instance is singleton_before


def test_test_runtime_accepts_test_uid_in_isolated_root(tmp_path):
    paths = DataPaths(mode="test", test_session_id="pytest_worker_0")
    paths._base = tmp_path
    resolved = paths.user_memory_root("uid_order_test")
    assert resolved.is_relative_to(tmp_path)
    assert resolved.name == "uid_order_test"


def test_classification_is_read_only(tmp_path):
    root = tmp_path / "runtime" / "memory"
    (root / "character" / "uid_order_test").mkdir(parents=True)
    (root / "character" / "owner").mkdir(parents=True)

    findings = classify_test_directories(root)
    assert findings == [
        {
            "char_id": "character",
            "user_id": "uid_order_test",
            "path": str(root / "character" / "uid_order_test"),
        }
    ]
    assert (root / "character" / "uid_order_test").is_dir()


def _client_for(router) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    fake_admin = TokenInfo(label="test-admin", scopes=frozenset({"admin"}))
    for route in router.routes:
        for dependency in route.dependant.dependencies:
            if hasattr(dependency.call, "_required_scopes"):
                app.dependency_overrides[dependency.call] = lambda: fake_admin
    return TestClient(app)


def test_status_exposes_test_mode_session_and_quarantined_users(sandbox):
    (sandbox.memory_char_root() / "uid_order_test").mkdir(parents=True)
    (sandbox.memory_char_root() / "owner").mkdir(parents=True)

    response = _client_for(system_router).get("/status")
    assert response.status_code == 200
    payload = response.json()
    assert payload["data_mode"] == "test"
    assert payload["test_session_id"] == sandbox.test_session_id
    assert payload["test_user_ids"] == ["uid_order_test"]
    assert payload["known_user_count"] == 1


def test_production_user_enumeration_filters_test_users(sandbox):
    (sandbox.memory_char_root() / "uid_order_test").mkdir(parents=True)
    (sandbox.memory_char_root() / "owner").mkdir(parents=True)

    response = _client_for(users_router).get("/")
    assert response.status_code == 200
    assert response.json()["users"] == ["owner"]


def test_status_fragment_contains_data_isolation_markers():
    root = Path(__file__).parents[1]
    page = (root / "admin" / "static" / "pages" / "status.html").read_text(encoding="utf-8")
    script = (root / "admin" / "static" / "js" / "status-users.js").read_text(encoding="utf-8")
    assert 'id="s-data-mode"' in page
    assert 'id="s-test-session"' in page
    assert 'id="s-test-users"' in page
    assert "d.test_session_id" in script
    assert "d.test_user_ids" in script
