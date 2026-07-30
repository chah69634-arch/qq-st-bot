"""Regression coverage for scheduler shells retired from the runtime protocol."""

from __future__ import annotations

import inspect


def test_retired_scheduler_names_are_not_registered_or_persisted(sandbox):
    from core.data_registry import REGISTRY
    from core.sandbox import get_paths
    from core.scheduler import loop
    from core.scheduler.proposer_registry import registered_trigger_names

    retired = {"activity_remind", "sleep_report"}
    assert retired.isdisjoint(loop._COOLDOWNS)
    assert retired.isdisjoint(registered_trigger_names())
    assert "sleep_end" in registered_trigger_names()
    assert "proactive_recent" not in REGISTRY
    assert not hasattr(get_paths(), "proactive_recent")
    assert not (sandbox.root_dir() / "runtime" / "proactive_recent.json").exists()
    assert not (sandbox.root_dir() / "runtime" / "proactive_recent.json.bak").exists()


def test_scheduler_startup_has_no_retired_state_path_read():
    from core.scheduler import loop

    assert "proactive_recent" not in inspect.getsource(loop)


def test_proactive_ledger_remains_the_runtime_state_file(sandbox):
    from core.scheduler import proactive_ledger as ledger

    ledger._loaded = False
    ledger.record_send("test_trigger", gist="sandbox ledger")

    assert sandbox.proactive_ledger().exists()
    assert not (sandbox.root_dir() / "runtime" / "proactive_recent.json").exists()
    assert not (sandbox.root_dir() / "runtime" / "proactive_recent.json.bak").exists()
