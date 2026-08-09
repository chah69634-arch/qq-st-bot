from pathlib import Path


ROOT = Path(__file__).parents[1]
PAGE = (ROOT / "admin" / "static" / "pages" / "dream-settings.html").read_text(
    encoding="utf-8"
)
SOURCE = (ROOT / "admin" / "static" / "js" / "dream-settings.js").read_text(
    encoding="utf-8"
)
CHARACTER_PAGE = (ROOT / "admin" / "static" / "pages" / "character.html").read_text(encoding="utf-8")
CHARACTER_SOURCE = (ROOT / "admin" / "static" / "js" / "character.js").read_text(encoding="utf-8")


def test_scenario_mode_reveals_the_hidden_authoring_panel():
    assert "mode === 'scenario' ? 'block' : 'none'" in SOURCE
    assert "mode === 'mirror' ? 'block' : 'none'" in SOURCE
    assert "dream-scenario-editor-card').style.display = 'block'" in SOURCE


def test_scenario_editor_is_structured_and_supports_json_exchange():
    assert 'id="ds-stages"' in PAGE
    assert 'id="ds-private-truths"' in PAGE
    assert 'id="ds-json-file"' in PAGE
    assert 'id="ds-yaml"' not in PAGE
    assert 'data-action="addDreamScenarioStage"' in PAGE
    assert 'data-action="importDreamScenarioJson"' in PAGE
    assert 'data-action="exportDreamScenarioJson"' in PAGE
    assert "{ document: documentValue }" in SOURCE
    assert "JSON.parse(await file.text())" in SOURCE
    assert "JSON.stringify(scenario, null, 2)" in SOURCE
    assert "_renderDreamScenarioPrivateTruths" in SOURCE
    assert "data-truth-policy" in SOURCE
    assert "reveal_required" in SOURCE


def test_character_editor_exposes_per_mode_dream_behavior():
    assert 'id="char-dream-identity-anchor"' in CHARACTER_PAGE
    assert 'id="char-dream-sandbox-directive"' in CHARACTER_PAGE
    assert 'id="char-dream-scenario-directive"' in CHARACTER_PAGE
    assert "presence_ext?.dream_behavior" in CHARACTER_SOURCE
    assert "presenceExt.dream_behavior = dreamBehavior" in CHARACTER_SOURCE
