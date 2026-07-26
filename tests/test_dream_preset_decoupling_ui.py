"""Static contract for Brief 118's independent dream-preset authoring UI."""

from pathlib import Path


ROOT = Path(__file__).parents[1]
PAGE = (ROOT / "admin" / "static" / "pages" / "dream-settings.html").read_text(encoding="utf-8")
SOURCE = (ROOT / "admin" / "static" / "js" / "dream-settings.js").read_text(encoding="utf-8")
I18N = (ROOT / "admin" / "static" / "i18n.js").read_text(encoding="utf-8")


def test_dream_preset_card_is_independent_from_world_selection():
    assert 'id="dream-preset-card"' in PAGE
    assert 'id="dream-preset-card" style="display:none"' not in PAGE
    assert 'id="dream-preset-select"' in PAGE
    assert 'data-action="createStandaloneDreamPreset"' in PAGE
    assert 'data-action="saveStandaloneDreamPresetSelection"' in PAGE

    world_change = SOURCE.split("function onDreamWorldChange()", 1)[1].split(
        "async function loadDreamLore()", 1
    )[0]
    assert "dream-preset-card" not in world_change
    assert "loadStandaloneDreamPreset" not in world_change


def test_dream_preset_ui_uses_independent_asset_and_settings_endpoints():
    for endpoint in (
        "'/dream/presets'",
        "`/dream/presets/${encodeURIComponent(_dreamCurrentPreset)}`",
        "'/dream/settings'",
    ):
        assert endpoint in SOURCE
    assert "loadDreamPreset()" not in SOURCE
    assert "saveDreamPreset()" not in SOURCE


def test_dream_preset_decoupling_copy_is_localized():
    for key in (
        "dream.preset.independent_title",
        "dream.preset.independent_hint",
        "dream.preset.save_selection",
        "dream.preset.save_content",
        "dynamic.dream.preset_selection_saved",
    ):
        assert PAGE.count(key) + SOURCE.count(f"'{key}'") + I18N.count(f"'{key}'") >= 3
