"""Contract guards for the public owner-turn v1 surface."""

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_owner_turn_contract_doc_covers_required_integration_rules():
    text = (ROOT / "docs" / "owner-turn-api.md").read_text(encoding="utf-8")
    for needle in (
        "POST /v1/owner/turns",
        "GET /v1/owner/turns/{client_turn_id}",
        "owner-input",
        "upload_id_not_available",
        "completed_result_expired",
        "execution_outcome_unknown",
        "curl",
        "PowerShell",
        "Python",
        "TypeScript",
    ):
        assert needle in text
    assert "C:\\Users\\" not in text
    assert "D:\\ai\\" not in text
    assert "emt_" in text and "emt_<redacted>" in text


def test_owner_turn_fixture_does_not_drift_from_documented_body():
    fixture = json.loads(
        (ROOT / "tests" / "protocol_fixtures" / "v1" / "owner_turn.json").read_text(
            encoding="utf-8"
        )
    )
    assert set(fixture["request"]["body"]) == {
        "client_turn_id",
        "message",
        "reply_to",
        "upload_ids",
    }
    assert any(response["status"] == 202 for response in fixture["responses"])
    assert any(response["status"] == 409 for response in fixture["responses"])


def test_owner_turn_request_schema_is_explicit_in_openapi():
    from admin.admin_server import app

    schema = app.openapi()
    operation = schema["paths"]["/v1/owner/turns"]["post"]
    request_schema = operation["requestBody"]["content"]["application/json"]["schema"]
    assert "$ref" in request_schema
    model = schema["components"]["schemas"][request_schema["$ref"].rsplit("/", 1)[-1]]
    assert set(model["properties"]) == {"client_turn_id", "message", "reply_to", "upload_ids"}
    assert set(model["additionalProperties"] for _ in [0]) == {False}
