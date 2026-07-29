"""C1.4 packaged public assets resolve without any legacy root."""

from __future__ import annotations

import json
from pathlib import Path

from core.data_paths import DataPaths


def _production_paths(tmp_path, monkeypatch) -> DataPaths:
    import core.sandbox as sandbox

    monkeypatch.chdir(tmp_path)
    paths = DataPaths(mode="production")
    monkeypatch.setattr(sandbox, "_instance", paths)
    return paths


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _seed_bundled(tmp_path: Path) -> None:
    _write(tmp_path / "bundled/characters/default/card.json", '{"name": "Bundled default"}')
    _write(tmp_path / "bundled/characters/default/activity_pool.yaml", "activities:\n  - name: bundled\n")
    _write(tmp_path / "bundled/characters/default/traits.yaml", "default_traits: []\n")
    _write(tmp_path / "bundled/characters/default/author_notes.json", "[]\n")
    _write(tmp_path / "bundled/seeds/reality/lorebook.yaml", "entries: []\n")
    _write(tmp_path / "bundled/seeds/reality/jailbreak_entries.json", '{"entries": []}\n')
    _write(tmp_path / "bundled/seeds/reality/relations.yaml", "default: {}\n")
    _write(tmp_path / "bundled/seeds/reality/blacklist.yaml", "[]\n")
    _write(tmp_path / "bundled/seeds/dream/worlds/_default/ruleset.md", "bundled rules\n")
    _write(tmp_path / "bundled/templates/dream_postcards/note.md", "bundled postcard\n")
    _write(tmp_path / "bundled/templates/character_template.json", '{"name": "template"}\n')


def test_fresh_layout_reads_packaged_default_and_seeds_without_legacy_roots(tmp_path, monkeypatch):
    paths = _production_paths(tmp_path, monkeypatch)
    _seed_bundled(tmp_path)

    assert not any((tmp_path / root).exists() for root in ("characters", "content", "defaults", "examples"))
    assert paths.activity_pool(char_id="default") == Path("bundled/characters/default/activity_pool.yaml")
    assert paths.yexuan_traits(char_id="default") == Path("bundled/characters/default/traits.yaml")
    assert paths.author_notes_pool(char_id="default") == Path("bundled/characters/default/author_notes.json")
    assert paths.default_dream_world_template_dir() == Path("bundled/seeds/dream/worlds/_default")

    from core.asset_registry import AssetRegistry
    from core.dream.postcard import _template_text

    default = AssetRegistry().resolve("default", "character")
    assert default.path() == Path("bundled/characters/default/card.json")
    assert default.label == "Bundled default"
    assert _template_text("note") == "bundled postcard\n"

    test_paths = DataPaths(mode="test", test_session_id="bundled_seed")
    test_paths._base = tmp_path / "runtime"
    assert test_paths.lorebook().read_text(encoding="utf-8") == "entries: []\n"
    assert json.loads(test_paths.jailbreak_entries().read_text(encoding="utf-8")) == {"entries": []}
    assert test_paths.relations().read_text(encoding="utf-8") == "default: {}\n"
    assert test_paths.blacklist().read_text(encoding="utf-8") == "[]\n"


def test_userdata_overrides_bundled_and_legacy_remains_final_fallback(tmp_path, monkeypatch):
    paths = _production_paths(tmp_path, monkeypatch)
    _seed_bundled(tmp_path)
    _write(tmp_path / "characters/default.json", '{"name": "Legacy default"}')
    _write(tmp_path / "content/characters/default/activity_pool.yaml", "activities:\n  - name: legacy\n")

    from core.asset_registry import AssetRegistry

    assert AssetRegistry().resolve("default", "character").label == "Bundled default"
    assert paths.activity_pool(char_id="default") == Path("bundled/characters/default/activity_pool.yaml")

    _write(tmp_path / "userdata/characters/cards/default.json", '{"name": "User default"}')
    _write(tmp_path / "userdata/characters/authored/default/activity_pool.yaml", "activities:\n  - name: user\n")
    assert AssetRegistry().resolve("default", "character").label == "User default"
    assert paths.activity_pool(char_id="default") == Path("userdata/characters/authored/default/activity_pool.yaml")


def test_legacy_public_roots_remain_readable_when_bundle_is_absent(tmp_path, monkeypatch):
    paths = _production_paths(tmp_path, monkeypatch)
    _write(tmp_path / "characters/default.json", '{"name": "Legacy default"}')
    _write(tmp_path / "content/characters/default/activity_pool.yaml", "activities:\n  - name: legacy\n")
    _write(tmp_path / "content/characters/default/traits.yaml", "default_traits: []\n")
    _write(tmp_path / "characters/default_author_notes.json", "[]\n")

    from core.asset_registry import AssetRegistry

    assert AssetRegistry().resolve("default", "character").label == "Legacy default"
    assert paths.activity_pool(char_id="default") == Path("content/characters/default/activity_pool.yaml")
    assert paths.yexuan_traits(char_id="default") == Path("content/characters/default/traits.yaml")
    assert paths.author_notes_pool(char_id="default") == Path("characters/default_author_notes.json")
