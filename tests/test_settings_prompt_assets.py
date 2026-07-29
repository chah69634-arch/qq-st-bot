def test_load_world_cards_handles_missing_resolved_world(monkeypatch):
    """A discovered world without a resolvable package keeps its fallback label."""
    import admin.routers.settings_prompt_assets as prompt_assets
    import core.dream.world_loader as world_loader

    monkeypatch.setattr(prompt_assets, "discover_worlds", lambda: ["missing-world"])
    monkeypatch.setattr(world_loader, "resolve_dream_world", lambda _world_id: None)

    assert prompt_assets._load_world_cards() == [{"id": "missing-world", "label": "missing-world"}]
