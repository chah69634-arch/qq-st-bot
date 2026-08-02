from core.tool_presets import normalize_tool_presets, resolve_tool_allowlist


def test_model_binding_resolves_named_allowlist():
    tools, name = resolve_tool_allowlist(
        {"tool_presets": [{"name": "minimal", "tools": ["get_time", "web_search"]}]},
        {"tool_preset": "minimal"},
    )
    assert name == "minimal"
    assert tools == {"get_time", "web_search"}


def test_missing_binding_fails_closed_but_unbound_preserves_legacy():
    assert resolve_tool_allowlist({"tool_presets": []}, {}) == (None, None)
    assert resolve_tool_allowlist({"tool_presets": []}, {"tool_preset": "deleted"}) == (set(), "deleted")


def test_normalize_discards_malformed_and_duplicate_presets():
    assert normalize_tool_presets([
        {"name": "one", "tools": ["a", "a"]},
        {"name": "one", "tools": ["b"]},
        {"name": "", "tools": []},
        {"name": "bad", "tools": "a"},
    ]) == [{"name": "one", "tools": ["a", "a"]}]
