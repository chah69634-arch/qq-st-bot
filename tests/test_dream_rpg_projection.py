from core.dream.rpg_projection import derive_snapshot


def _event(seq, branch, *, public=(), player=(), character=(), private=(), scene=()):
    return {"seq": seq, "branch_id": branch, "event_type": "resolution", "projections": {
        "public": list(public), "player": list(player), "character": list(character), "kp_private": list(private),
    }, "scene_updates": list(scene)}


def test_projection_never_crosses_visibility_boundaries():
    snapshot = derive_snapshot([_event(1, "root", public=({"fact_id": "door", "value": "open"},), player=({"fact_id": "key", "value": "found"},), character=({"fact_id": "suspect", "value": "watchful", "knowledge": "suspected"},), private=({"fact_id": "trap", "value": "armed"},))], active_branch_id="root", revision=1)
    assert snapshot["shared_facts"] == {"door": {"value": "open", "knowledge": None}}
    assert "key" not in snapshot["shared_facts"]
    assert snapshot["character_knowledge"]["suspect"]["knowledge"] == "suspected"
    assert "trap" not in snapshot["player_known_facts"]


def test_branch_snapshot_inherits_only_pre_branch_events():
    events = [_event(1, "root", public=({"fact_id": "a", "value": "old"},)), _event(2, "root", public=({"fact_id": "b", "value": "removed"},)), {"seq": 3, "branch_id": "root", "event_type": "branch_created", "payload": {"new_branch_id": "branch_new", "parent_branch_id": "root", "base_seq": 1}}, _event(4, "branch_new", public=({"fact_id": "c", "value": "new"},))]
    snapshot = derive_snapshot(events, active_branch_id="branch_new", revision=2)
    assert set(snapshot["shared_facts"]) == {"a", "c"}


def test_character_knowledge_keeps_each_explicit_state_and_public_facts_persist():
    events = [
        _event(1, "root", public=({"fact_id": "door", "value": "open"},), character=({"fact_id": "unknown", "value": "x", "knowledge": "unknown"},)),
        _event(2, "root", character=({"fact_id": "suspected", "value": "x", "knowledge": "suspected"},)),
        _event(3, "root", character=({"fact_id": "known", "value": "x", "knowledge": "known"},)),
        _event(4, "root", character=({"fact_id": "misbelieved", "value": "x", "knowledge": "misbelieved"},)),
    ]
    snapshot = derive_snapshot(events, active_branch_id="root", revision=4)
    assert snapshot["shared_facts"]["door"]["value"] == "open"
    assert {key: fact["knowledge"] for key, fact in snapshot["character_knowledge"].items()} == {
        "unknown": "unknown", "suspected": "suspected", "known": "known", "misbelieved": "misbelieved",
    }
