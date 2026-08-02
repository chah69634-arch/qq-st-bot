"""Regression coverage for SEC-AUTH-2 audit-path isolation."""

import json

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from admin import audit
from admin.auth import TokenInfo, require_scopes


def _app_with_protected_route() -> FastAPI:
    app = FastAPI()

    @app.get("/protected")
    async def protected(_info: TokenInfo = Depends(require_scopes("admin"))):
        return {"ok": True}

    return app


def test_auth_failure_audit_writes_to_active_test_sandbox(sandbox):
    """A real 401 still audits, but never resolves the production data root."""
    with TestClient(_app_with_protected_route()) as client:
        response = client.get("/protected")

    assert response.status_code == 401
    audit_log = sandbox.auth_audit_log()
    assert audit_log.is_file()
    record = json.loads(audit_log.read_text(encoding="utf-8").splitlines()[-1])
    assert record["event"] == "auth_failed"
    assert record["path"] == "/protected"

