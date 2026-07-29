"""C1.3 dry-run: migration inventory is resolver-aligned and input read-only."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path


def _module():
    path = Path(__file__).parents[1] / "scripts" / "authored_root_migration_dry_run.py"
    spec = importlib.util.spec_from_file_location("authored_root_migration_dry_run", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write(path: Path, content: bytes | str = "x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")
    return path


def _records(manifest: dict, category: str) -> dict[str, dict]:
    return {record["logical_id"]: record for record in manifest["resources"] if record["category"] == category}


def test_dry_run_classifies_assets_completeness_and_keeps_inputs_unchanged(tmp_path):
    module = _module()
    repo = tmp_path / "install"
    user = repo / "userdata"

    # Cards cover canonical-only, legacy-only, exact, diverged, invalid, and ID collision.
    _write(user / "characters/cards/user.json", '{}')
    _write(repo / "characters/legacy.json", '{}')
    _write(user / "characters/cards/exact.json", '{}')
    _write(repo / "characters/exact.json", '{}')
    _write(user / "characters/cards/diverged.json", '{"v": 1}')
    _write(repo / "characters/diverged.json", '{"v": 2}')
    _write(user / "characters/cards/broken.json", '{broken')
    _write(repo / "characters/broken.json", '{}')
    _write(repo / "characters/collision.json", '{}')
    _write(repo / "characters/collision.md", 'card')
    _write(repo / "characters/default.json", '{}')
    _write(repo / "content/characters/default/traits.yaml", 'seed: true')
    _write(repo / "characters/memeval_generated.json", '{}')

    # Resource-level assets include a normal legacy authored file and a Chinese stable preset ID.
    _write(repo / "content/characters/role/knowledge/fact.md", 'legacy fact')
    _write(user / "characters/dream/presets/审讯.md", 'preset')
    _write(user / "assets/stickers/happy/a.png", b"\x89PNG\r\n\x1a\nasset")

    # The selected user world is intentionally incomplete; legacy is complete but must not be merged.
    _write(user / "characters/dream/worlds/space/ruleset.md", 'rules')
    _write(repo / "characters/dream_worlds/space/ruleset.md", 'legacy rules')
    _write(repo / "characters/dream_worlds/space/mes_example.md", 'legacy example')
    _write(repo / "characters/dream_worlds/space/vocab.json", '[]')
    _write(repo / "characters/dream_worlds/legacy_only/ruleset.md", 'rules')

    _write(repo / "data/runtime/active_prompt_assets.json", json.dumps({
        "active_character": "legacy", "enabled_lorebooks": [], "enabled_jailbreaks": [],
        "active_dream_preset": "interrogation",
    }))
    _write(repo / "config.yaml", "tts:\n  gpt_model_path: characters/legacy-model.ckpt\n")
    before = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in repo.rglob("*") if path.is_file()}

    manifest = module.build_manifest(repo)
    again = module.build_manifest(repo)

    assert manifest == again
    cards = _records(manifest, "character_card")
    assert cards["user"]["status"] == "canonical-only"
    assert cards["legacy"]["status"] == "legacy-only"
    assert cards["legacy"]["active_reference"] == ["active-character"]
    assert cards["exact"]["status"] == "exact-duplicate"
    assert cards["diverged"]["status"] == "diverged"
    assert cards["broken"]["status"] == "invalid-canonical"
    assert cards["collision"]["status"] == "unresolved-id"
    assert "default" not in cards
    assert "default/traits.yaml" not in _records(manifest, "authored_character")
    assert _records(manifest, "generated_fixture")["memeval_generated"]["status"] == "ignored-generated-fixture"
    assert _records(manifest, "dream_preset")["interrogation"]["active_reference"] == ["active-dream-preset"]
    worlds = _records(manifest, "dream_world")
    assert worlds["space"]["status"] == "incomplete-canonical-package"
    assert worlds["space"]["completeness"]["required_fields_missing"] == ["mes_example.md", "vocab.json"]
    assert worlds["space"]["recommended_action"] == "manual-review"
    assert worlds["legacy_only"]["status"] == "incomplete-legacy-package"
    sticker = _records(manifest, "sticker")["happy/a.png"]
    assert sticker["canonical_size"] == len(b"\x89PNG\r\n\x1a\nasset")
    assert len(sticker["canonical_sha256"]) == 64
    assert manifest["config_references"] == [{
        "path": "legacy/<redacted>", "reference_type": "tts.gpt_model_path",
        "source": "legacy", "status": "active-legacy-reference",
    }]
    assert all("install" not in json.dumps(record, ensure_ascii=False) for record in manifest["resources"])
    after = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in repo.rglob("*") if path.is_file()}
    assert after == before


def test_dry_run_matches_production_registry_precedence_and_cli_failures(tmp_path, monkeypatch):
    module = _module()
    repo = tmp_path / "install"
    _write(repo / "characters/reality/lorebooks/base.yaml", "legacy: true")
    _write(repo / "userdata/characters/reality/lorebooks/base.yaml", "user: true")
    _write(repo / "characters/dream_presets/审讯.md", "legacy")
    _write(repo / "userdata/characters/dream/presets/审讯.md", "user")

    monkeypatch.chdir(repo)
    import core.sandbox as sandbox
    from core.asset_registry import AssetRegistry
    from core.data_paths import DataPaths

    monkeypatch.setattr(sandbox, "_instance", DataPaths(mode="production"))
    registry = AssetRegistry()
    manifest = module.build_manifest(repo)
    lore = _records(manifest, "reality_lorebook")["base"]
    preset = _records(manifest, "dream_preset")["interrogation"]
    assert registry.resolve("base", "reality_lorebook").source_path.resolve() == (repo / "userdata/characters/reality/lorebooks/base.yaml").resolve()
    assert registry.resolve("interrogation", "dream_preset").source_path.resolve() == (repo / "userdata/characters/dream/presets/审讯.md").resolve()
    assert lore["effective_read_source"] == "user" and lore["status"] == "diverged"
    assert preset["effective_read_source"] == "user" and preset["status"] == "diverged"

    json_output = tmp_path / "report.json"
    markdown_output = tmp_path / "report.md"
    assert module.main(["--repo-root", str(repo), "--json-output", str(json_output), "--markdown-output", str(markdown_output), "--fail-on-diverged"]) == 2
    assert json.loads(json_output.read_text(encoding="utf-8"))["schema_version"] == module.SCHEMA_VERSION
    assert "Authored Root Migration Dry-Run" in markdown_output.read_text(encoding="utf-8")
    direct_output = tmp_path / "direct-report.json"
    result = subprocess.run(
        [sys.executable, str(Path(module.__file__)), "--repo-root", str(repo), "--json-output", str(direct_output)],
        cwd=repo, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(direct_output.read_text(encoding="utf-8"))["schema_version"] == module.SCHEMA_VERSION
