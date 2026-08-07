import json
from pathlib import Path


def test_autonomy_fixture_covers_required_opportunity_types():
    fixture_path = Path(__file__).parent / "autonomy_eval" / "fixtures.json"
    rows = json.loads(fixture_path.read_text(encoding="utf-8"))
    assert {row["id"] for row in rows} == {
        "routine",
        "care",
        "unfinished_topic",
        "memory_reactivation",
        "no_op",
    }


def test_opportunity_context_marks_candidate_evidence_and_system_clock():
    from core.autonomy.models import Job, Opportunity, Signal
    from core.autonomy.runner import _opportunity_context

    opportunity = Opportunity.merge([
        Signal(
            source="interval",
            evidence=[{"fact": "elapsed", "observed_at": 123.0}],
            reason="interval elapsed",
            memory_query=None,
        )
    ], now=100.0)
    rendered = _opportunity_context(Job(uid="owner", char_id="char", source="autonomy", opportunity=opportunity.to_dict()))
    payload = json.loads(rendered.split(": ", 1)[1])
    assert payload["candidate_evidence_policy"]
    assert payload["signals"][0]["evidence_semantics"] == "candidate_system_fact_not_dialogue"
    assert payload["reality_time_facts"]["source"] == "system_clock"


def test_memory_query_is_system_executed_and_keeps_provenance(monkeypatch):
    from core.autonomy.runner import _memory_query_message
    import core.memory.episodic_memory as episodic_memory

    calls = []

    def retrieve(*args, **kwargs):
        calls.append((args, kwargs))
        return ([{
            "id": "episode-1",
            "narrative_summary": "The owner described a project milestone.",
            "occurred_at": 100.0,
            "timestamp": 110.0,
            "strength": 0.8,
            "speaker_id": "owner",
            "source_turn_ids": ["turn-1"],
        }], [{"id": "episode-1", "selected": True}])

    monkeypatch.setattr(episodic_memory, "retrieve", retrieve)
    message = _memory_query_message("owner", "char", {"topic": "project milestone"}, now=200.0)
    assert calls[0][1]["allow_strengthen"] is False
    assert calls[0][1]["return_trace"] is True
    assert message["_layer"] == "autonomy_memory_query"
    assert '"source": "episodic"' in message["content"]
    assert '"occurred_at": 100.0' in message["content"]
    assert '"speaker_provenance": "owner"' in message["content"]


def test_no_anchor_rejects_memory_claim_but_allows_current_observation():
    from core.autonomy.runner import _talk_text_has_unsupported_memory_claim

    assert _talk_text_has_unsupported_memory_claim("I remember you said this", memory_anchor_available=False)
    assert _talk_text_has_unsupported_memory_claim("我记得你说过这个", memory_anchor_available=False)
    assert not _talk_text_has_unsupported_memory_claim("It is quiet right now", memory_anchor_available=False)
    assert not _talk_text_has_unsupported_memory_claim("I remember you said this", memory_anchor_available=True)


def test_low_confidence_memory_is_not_a_reliable_anchor(monkeypatch):
    from core.autonomy.runner import _memory_anchor_available, _memory_query_message
    import core.memory.episodic_memory as episodic_memory

    monkeypatch.setattr(episodic_memory, "retrieve", lambda *args, **kwargs: ([{
        "id": "weak",
        "summary": "A weakly scored candidate.",
        "occurred_at": 100.0,
        "timestamp": 101.0,
        "speaker_id": "owner",
        "strength": 0.2,
    }], []))
    assert not _memory_anchor_available([_memory_query_message("owner", "char", "weak", now=200.0)])


def test_tool_fact_and_hardware_state_are_distinct_grounded_layers(monkeypatch):
    from core.autonomy.runner import _hardware_job_message, _tool_fact_message
    import core.hardware.jobs as jobs

    monkeypatch.setattr(jobs, "format_prompt", lambda: "<hardware>job-1 active</hardware>")
    hardware = _hardware_job_message(now=200.0)
    tool = _tool_fact_message("get_time", "12:00", "ok", now=200.0)
    assert hardware["_layer"] == "autonomy_hardware_jobs"
    assert tool["_layer"] == "autonomy_tool_fact"
    assert "job-1 active" in hardware["content"]
    assert '"tool_name": "get_time"' in tool["content"]


def test_final_prompt_snapshot_contains_opportunity_recall_and_disposition(sandbox, monkeypatch):
    import asyncio
    from types import SimpleNamespace

    from core.autonomy import runner, store
    from core.autonomy.models import Job, Opportunity, Run, Signal

    state = store.load("owner", "char")
    state["config"]["enabled"] = True
    monkeypatch.setattr(runner.policy, "admission", lambda *args: None)
    monkeypatch.setattr(runner.policy, "allowed_tools", lambda *args: [])
    monkeypatch.setattr(runner.talk_gate, "check", lambda *args, **kwargs: ("hard", "suppressed_unanswered_cap"))
    monkeypatch.setattr(runner, "_user_became_active", lambda _uid: False)

    async def chat_turn(*_args, **_kwargs):
        return SimpleNamespace(tool_calls=[], continuation_items=[], assistant_message={})

    monkeypatch.setattr("core.llm_client.chat_turn", chat_turn)
    opportunity = Opportunity.merge([
        Signal(source="interval", reason="interval elapsed", memory_query={"topic": "missing"})
    ]).to_dict()
    run = asyncio.run(runner._run_locked(
        Job(uid="owner", char_id="char", source="autonomy", opportunity=opportunity),
        state,
        Run(uid="owner", char_id="char", source="autonomy", job_id="job"),
    ))
    layers = {item.get("_layer") for item in run.prompt_snapshot}
    assert {"autonomy_opportunity", "autonomy_memory_query", "autonomy_final_disposition"} <= layers
    final = next(item for item in run.prompt_snapshot if item.get("_layer") == "autonomy_final_disposition")
    assert '"disposition": "completed_no_op"' in final["content"]
