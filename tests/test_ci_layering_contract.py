from pathlib import Path


WORKFLOW_ROOT = Path(__file__).parents[1] / ".github" / "workflows"


def test_pr_workflow_keeps_smoke_and_protocol_contracts_parallel():
    workflow = (WORKFLOW_ROOT / "tests.yml").read_text(encoding="utf-8")
    assert "pull_request" in workflow
    assert "python -m pytest -n auto -q" in workflow
    assert "tests/test_protocol_fixtures.py" in workflow
    assert "full-pytest:" in workflow
    assert "--junitxml=artifacts/pytest-" in workflow
    assert "continue-on-error" not in workflow


def test_external_and_manual_evidence_are_separate_from_pr_required_checks():
    evals = (WORKFLOW_ROOT / "offline-evals.yml").read_text(encoding="utf-8")
    manual = (WORKFLOW_ROOT / "manual-sensor-evidence.yml").read_text(encoding="utf-8")
    assert "run_coplay" in evals
    assert "inputs.run_coplay == true" in evals
    assert "cost_boundary=explicit workflow_dispatch opt-in" in evals
    assert '"level": "manual"' in manual
    assert "evidence_location" in manual
