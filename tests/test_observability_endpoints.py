from __future__ import annotations

import json

from fastapi.testclient import TestClient


SECRET = "observability-test-admin-secret"


def _headers():
    return {"Authorization": f"Bearer {SECRET}"}


def _client(monkeypatch):
    monkeypatch.setattr("admin.auth.get_admin_secret", lambda: SECRET)
    from admin.admin_server import app
    return TestClient(app, raise_server_exceptions=False)


def _active(sandbox):
    sandbox.active_prompt_assets().parent.mkdir(parents=True, exist_ok=True)
    sandbox.active_prompt_assets().write_text(json.dumps({"active_character": "yexuan"}), encoding="utf-8")


def test_growth_endpoints_empty_and_auth(sandbox, monkeypatch):
    _active(sandbox)
    client = _client(monkeypatch)
    assert client.get("/growth/interests").status_code == 401
    assert client.get("/growth/interests", headers=_headers()).json()["interests"] == []
    assert client.get("/growth/works/not_real", headers=_headers()).json()["entries"] == []
    assert client.get("/growth/notes/not_real", headers=_headers()).json()["entries"] == []
    assert client.get("/growth/practice-log", headers=_headers()).json()["entries"] == []


def test_work_reader_is_index_bounded(sandbox, monkeypatch):
    _active(sandbox)
    client = _client(monkeypatch)
    root = sandbox.growth_works_dir("int_test", char_id="yexuan")
    root.mkdir(parents=True)
    (root / "index.json").write_text(json.dumps([{"file": "20260712_1.md", "date": "2026-07-12"}]), encoding="utf-8")
    (root / "20260712_1.md").write_text("作品正文", encoding="utf-8")
    ok = client.get("/growth/works/int_test/20260712_1.md", headers=_headers())
    assert ok.status_code == 200 and ok.json()["content"] == "作品正文"
    assert client.get("/growth/works/int_test/not-in-index.md", headers=_headers()).status_code == 404
    assert client.get("/growth/works/int_test/..%2Fsecret.md", headers=_headers()).status_code in (404, 422)


def test_visual_spend_digest_and_group_empty_views(sandbox, monkeypatch):
    _active(sandbox)
    client = _client(monkeypatch)
    assert client.get("/perception/visual-trace", headers=_headers()).json()["entries"] == []
    assert client.get("/perception/visual-trace?date=bad", headers=_headers()).status_code == 422
    assert client.get("/spend/mandates", headers=_headers()).json()["entries"] == []
    assert client.get("/memory/digest/u1", headers=_headers()).json()["content"] == ""


def test_debug_recall_alias_is_authenticated_and_empty_safe(sandbox, monkeypatch):
    _active(sandbox)
    client = _client(monkeypatch)
    assert client.get("/debug/recall?uid=u1").status_code == 401
    response = client.get("/debug/recall?uid=u1&char_id=yexuan", headers=_headers())
    assert response.status_code == 200
    payload = response.json()
    assert payload["uid"] == "u1"
    assert payload["char_id"] == "yexuan"
    assert payload["records"] == []


# ── 资源完整性检查 / API 契约检查（2026-07-25，茶茶反馈 item 9/10）────────────

def test_resource_completeness_requires_auth_and_returns_shape(sandbox, monkeypatch):
    _active(sandbox)
    client = _client(monkeypatch)
    assert client.get("/observability/resource-completeness").status_code == 401

    payload = client.get("/observability/resource-completeness", headers=_headers()).json()
    assert "checks" in payload and "summary" in payload and "known_gaps" in payload
    assert len(payload["checks"]) > 0
    for c in payload["checks"]:
        assert c["status"] in ("ok", "off", "missing_asset", "unknown")
    assert len(payload["known_gaps"]) > 0
    for g in payload["known_gaps"]:
        assert g["id"] and g["label"] and g["source"]


def test_resource_completeness_single_check_failure_is_isolated(sandbox, monkeypatch):
    """单项检查抛异常时，只影响那一项（status=unknown），不得拖垮整体接口。"""
    _active(sandbox)
    client = _client(monkeypatch)

    def _boom():
        raise RuntimeError("模拟检查崩溃")

    import core.resource_completeness as _rc
    monkeypatch.setattr(_rc, "_CHECKS", [("boom", "崩溃项", _boom), *_rc._CHECKS[1:]])

    response = client.get("/observability/resource-completeness", headers=_headers())
    assert response.status_code == 200
    payload = response.json()
    boom_check = next(c for c in payload["checks"] if c["id"] == "boom")
    assert boom_check["status"] == "unknown"
    assert len(payload["checks"]) == len(_rc._CHECKS)


def test_api_contract_check_requires_auth_and_returns_shape(sandbox, monkeypatch):
    _active(sandbox)
    client = _client(monkeypatch)
    assert client.get("/observability/api-contract-check").status_code == 401

    payload = client.get("/observability/api-contract-check", headers=_headers()).json()
    assert "frontend_available" in payload
    assert "backend_producible" in payload
    assert payload["status"] in ("ok", "drift_detected", "frontend_unavailable")


def test_api_contract_check_gracefully_skips_when_frontend_repo_missing(sandbox, monkeypatch):
    _active(sandbox)
    client = _client(monkeypatch)

    import core.api_contract_check as _acc
    monkeypatch.setattr(_acc, "_find_frontend_repo", lambda: None)

    payload = client.get("/observability/api-contract-check", headers=_headers()).json()
    assert payload["frontend_available"] is False
    assert payload["status"] == "frontend_unavailable"
    # 前端不可用时不应报错崩溃，且后端侧扫描仍应产出（不因前端缺失而跳过自己的那一半）
    assert "backend_producible" in payload


def test_api_contract_check_detects_injected_drift(sandbox, monkeypatch, tmp_path):
    """回归造假：伪造一个前端仓库，只认识部分 type，验证 broken 列表能抓出缺口。"""
    _active(sandbox)
    client = _client(monkeypatch)

    fake_repo = tmp_path / "fake_frontend"
    ws_dir = fake_repo / "src" / "shared" / "api"
    ws_dir.mkdir(parents=True)
    (ws_dir / "ws.ts").write_text(
        "class WSClient {\n"
        "  private async _dispatchAction(type, action) {\n"
        "    switch (type) {\n"
        "      case 'minimize_window':\n"
        "        return;\n"
        "      default:\n"
        "        throw new Error('unsupported');\n"
        "    }\n"
        "  }\n"
        "}\n",
        encoding="utf-8",
    )

    import core.api_contract_check as _acc
    monkeypatch.setattr(_acc, "_find_frontend_repo", lambda: fake_repo)

    payload = client.get("/observability/api-contract-check", headers=_headers()).json()
    assert payload["frontend_available"] is True
    assert payload["status"] == "drift_detected"
    assert "show_notify" in payload["broken"], "假前端只认 minimize_window，show_notify 应报漂移"
    assert "media_play_pause" in payload["broken"]
