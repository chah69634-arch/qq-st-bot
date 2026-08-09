from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from admin.auth import TokenInfo
from admin.routers.settings_misc import router as settings_misc_router


@pytest.fixture
def admin_client():
    app = FastAPI()
    app.include_router(settings_misc_router)
    fake_admin = TokenInfo(label="dream-ablation-test", scopes=frozenset({"admin"}))
    for route in settings_misc_router.routes:
        for dependency in route.dependant.dependencies:
            if hasattr(dependency.call, "_required_scopes"):
                app.dependency_overrides[dependency.call] = lambda: fake_admin
    return TestClient(app)


def _reset_cache():
    import core.dream.dream_prompt_ablation as ablation

    ablation._cache = None
    ablation._cache_mtime = None


def _build(capture: dict):
    from core.dream.dream_prompt import build_dream_prompt

    character = SimpleNamespace(
        name="Ablation Character",
        gender="neutral",
        system_prompt="IDENTITY_MARKER",
        description="",
        personality="",
        presence_ext={},
    )
    return build_dream_prompt(
        character=character,
        user_id="dream_ablation_user",
        user_message="CURRENT_USER_MARKER",
        context_snapshot={},
        dream_history=[{"role": "assistant", "content": "HISTORY_MARKER"}],
        local_state={},
        _capture_hook=capture.update,
    )


def test_dream_ablation_filters_identity_and_history_only_after_assembly(sandbox):
    from core.dream.dream_prompt_ablation import set_state

    _reset_cache()
    set_state(["D1_identity_core", "D8_dream_director", "D9_dream_history"])
    capture = {}
    messages = _build(capture)
    combined = "\n".join(message["content"] for message in messages)

    assert "IDENTITY_MARKER" not in combined
    assert "HISTORY_MARKER" not in combined
    assert "CURRENT_USER_MARKER" in combined
    assert "/stop" in combined
    assert "梦境导演注记" not in combined
    assert "DX·梦境退出协议" in combined
    assert capture["ablated_layers"] == ["D1_identity_core", "D8_dream_director", "D9_dream_history"]
    by_label = {layer["label"]: layer for layer in capture["layers"]}
    assert by_label["D1_identity_core"]["injected"] is False
    assert "ABLATED" in by_label["D1_identity_core"]["flags"]
    assert by_label["D9_dream_history"]["injected"] is False


def test_dream_ablation_rejects_protocol_and_current_user_layers(sandbox):
    from core.dream.dream_prompt_ablation import set_state

    _reset_cache()
    with pytest.raises(ValueError, match="不可消融层"):
        set_state(["DX_exit_protocol"])
    with pytest.raises(ValueError, match="不可消融层"):
        set_state(["D10_user_message"])


def test_dream_ablation_api_round_trip(sandbox, admin_client):
    _reset_cache()
    response = admin_client.put(
        "/dream-prompt-ablation",
        json={"disabled_layers": ["D0_jailbreak", "DS_scenario"]},
    )
    assert response.status_code == 200
    state = admin_client.get("/dream-prompt-ablation")
    assert state.status_code == 200
    payload = state.json()
    assert payload["disabled_layers"] == ["D0_jailbreak", "DS_scenario"]
    assert "DX_exit_protocol" in payload["always_on"]


def test_dream_ablation_api_rejects_unknown_layer(sandbox, admin_client):
    _reset_cache()
    response = admin_client.put(
        "/dream-prompt-ablation",
        json={"disabled_layers": ["not_a_dream_layer"]},
    )
    assert response.status_code == 422
