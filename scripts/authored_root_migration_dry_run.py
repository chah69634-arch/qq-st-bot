"""Read-only C1.3 authored-root migration inventory.

This command deliberately has no apply mode.  It compares the private
``userdata`` authored root with the legacy roots using the same layered
resolver used by the running service, emits a deterministic manifest, and
never changes an input asset.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Iterable

# ``python scripts/...py`` puts scripts/ (not the repository) on sys.path.
# Add the source root so the command works exactly as documented.
_SOURCE_ROOT = Path(__file__).resolve().parents[1]
if str(_SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(_SOURCE_ROOT))

try:
    import yaml
except ModuleNotFoundError:  # pragma: no cover - production installs include PyYAML
    yaml = None

from core.asset_registry import _dream_preset_logical_id
from core.authored_asset_resolver import resolve_layered_directories, resolve_layered_files


SCHEMA_VERSION = "presencekit.authored-root-migration-dry-run.v1"
_TEXT_SUFFIXES = frozenset({".json", ".yaml", ".yml", ".md", ".txt"})
_CARD_SUFFIXES = (".json", ".txt", ".md")
_BINARY_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp", ".gif", ".wav", ".mp3", ".ogg", ".pth", ".ckpt", ".bin", ".onnx", ".safetensors"})
_DREAM_REQUIRED = ("ruleset.md", "mes_example.md", "vocab.json")
_DREAM_OPTIONAL = ("lorebook.yaml", "symbolic_profile.yaml", "hud_labels.yaml", "scene_labels.yaml", "meta.json")


def _path_alias(path: Path, *, repo_root: Path, userdata_root: Path, legacy_root: Path) -> str:
    """Return an alias-relative path; never expose an installation absolute path."""
    resolved = path.resolve(strict=False)
    for alias, root in (("userdata", userdata_root), ("legacy", legacy_root), ("repo", repo_root)):
        try:
            return f"{alias}/{resolved.relative_to(root.resolve(strict=False)).as_posix()}"
        except ValueError:
            pass
    return "external/<redacted>"


def _sha256(path: Path) -> str | None:
    try:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None


def _size(path: Path | None) -> int | None:
    if path is None:
        return None
    try:
        return path.stat().st_size
    except OSError:
        return None


def _is_valid_file(path: Path | None) -> tuple[bool, str | None]:
    """Validate syntax where the loader has a structured contract; never retain text."""
    if path is None:
        return True, None
    try:
        if path.stat().st_size == 0:
            return False, "empty-file"
        suffix = path.suffix.lower()
        if suffix == ".json":
            with path.open("r", encoding="utf-8") as handle:
                json.load(handle)
        elif suffix in {".yaml", ".yml"}:
            if yaml is None:
                return True, "yaml-validation-unavailable"
            with path.open("r", encoding="utf-8") as handle:
                yaml.safe_load(handle)
        elif suffix in {".md", ".txt"}:
            with path.open("r", encoding="utf-8") as handle:
                if not handle.read(1):
                    return False, "empty-file"
        # Images, audio, and models are deliberately only stat'ed and hashed.
        return True, None
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError, Exception) as exc:
        # The broad guard is intentional: this report must fail-soft per asset.
        return False, type(exc).__name__


def _package_fingerprint(root: Path | None) -> tuple[str | None, int | None]:
    if root is None or not root.is_dir():
        return None, None
    entries: list[tuple[str, str, int]] = []
    try:
        for path in sorted((p for p in root.rglob("*") if p.is_file()), key=lambda p: p.relative_to(root).as_posix().casefold()):
            digest = _sha256(path)
            size = _size(path)
            if digest is None or size is None:
                return None, None
            entries.append((path.relative_to(root).as_posix(), digest, size))
    except OSError:
        return None, None
    payload = "".join(f"{name}\0{digest}\0{size}\n" for name, digest, size in entries).encode("utf-8")
    return hashlib.sha256(payload).hexdigest(), sum(size for _, _, size in entries)


def _package_completeness(root: Path | None, *, selected_default: Path | None) -> dict[str, Any]:
    present = set()
    if root is not None and root.is_dir():
        present = {p.name for p in root.iterdir() if p.is_file()}
    required_missing = [name for name in _DREAM_REQUIRED if name not in present]
    optional_missing = [name for name in _DREAM_OPTIONAL if name not in present]
    fallback_dependencies = [
        name for name in required_missing
        if selected_default is not None and (selected_default / name).is_file()
    ]
    return {
        "required_fields_missing": required_missing,
        "optional_fields_missing": optional_missing,
        "fallback_dependencies": fallback_dependencies,
        "depends_on_selected_root_default": bool(fallback_dependencies),
        "independently_materializable": not required_missing,
    }


def _base_record(
    *, category: str, logical_id: str, key: str, canonical: Path | None, legacy: Path | None,
    canonical_kind: str, legacy_kind: str, repo_root: Path, userdata_root: Path, legacy_root: Path,
    active_references: set[str] | None = None,
) -> dict[str, Any]:
    canonical_ok, canonical_error = _is_valid_file(canonical) if canonical is not None and canonical.is_file() else (True, None)
    legacy_ok, legacy_error = _is_valid_file(legacy) if legacy is not None and legacy.is_file() else (True, None)
    canonical_hash = _sha256(canonical) if canonical is not None and canonical.is_file() else None
    legacy_hash = _sha256(legacy) if legacy is not None and legacy.is_file() else None
    return {
        "category": category,
        "logical_id": logical_id,
        "relative_resource_key": key,
        "canonical_path_kind": canonical_kind,
        "legacy_path_kind": legacy_kind,
        "canonical_path": _path_alias(canonical, repo_root=repo_root, userdata_root=userdata_root, legacy_root=legacy_root) if canonical else None,
        "legacy_path": _path_alias(legacy, repo_root=repo_root, userdata_root=userdata_root, legacy_root=legacy_root) if legacy else None,
        "canonical_exists": canonical is not None,
        "legacy_exists": legacy is not None,
        "canonical_sha256": canonical_hash,
        "legacy_sha256": legacy_hash,
        "canonical_size": _size(canonical),
        "legacy_size": _size(legacy),
        "canonical_validation_error": canonical_error,
        "legacy_validation_error": legacy_error,
        "effective_read_source": "user" if canonical is not None else ("legacy" if legacy is not None else None),
        "active_reference": sorted(active_references or ()),
        "completeness": {},
        "status": "unresolved-id",
        "recommended_action": "manual-review",
        "reason": canonical_error or legacy_error or "not-classified",
    }


def _classify(record: dict[str, Any], *, package: bool = False) -> None:
    canonical = bool(record["canonical_exists"])
    legacy = bool(record["legacy_exists"])
    canonical_valid = record.get("canonical_validation_error") is None
    legacy_valid = record.get("legacy_validation_error") is None
    # Package validity is represented by completeness rather than a file parser.
    if package:
        missing = record["completeness"].get("required_fields_missing", [])
        if canonical and missing:
            record.update(status="incomplete-canonical-package", recommended_action="manual-review", reason="required-dream-fields-missing")
            return
        if legacy and not canonical and missing:
            record.update(status="incomplete-legacy-package", recommended_action="preserve-forensics", reason="required-dream-fields-missing")
            return
    if canonical and not canonical_valid:
        record.update(status="invalid-canonical", recommended_action="manual-recovery-review", reason=record["canonical_validation_error"])
    elif legacy and not legacy_valid and not canonical:
        record.update(status="invalid-legacy", recommended_action="preserve-forensics", reason=record["legacy_validation_error"])
    elif canonical and legacy:
        if record["canonical_sha256"] == record["legacy_sha256"]:
            record.update(status="exact-duplicate", recommended_action="canonical-confirmed", reason="same-sha256")
        else:
            record.update(status="diverged", recommended_action="manual-review", reason="same-logical-id-different-content")
    elif canonical:
        record.update(status="canonical-only", recommended_action="keep", reason="only-in-userdata")
    elif legacy:
        record.update(status="legacy-only", recommended_action="candidate-copy-to-userdata", reason="only-in-legacy")


def _files(root: Path, suffixes: Iterable[str] | None = None, *, recursive: bool = True) -> list[Path]:
    if not root.is_dir():
        return []
    allowed = {s.lower() for s in suffixes} if suffixes is not None else None
    iterator = root.rglob("*") if recursive else root.glob("*")
    return sorted((p for p in iterator if p.is_file() and (allowed is None or p.suffix.lower() in allowed)), key=lambda p: p.relative_to(root).as_posix().casefold())


def _active_references(repo_root: Path) -> tuple[dict[tuple[str, str], set[str]], list[dict[str, Any]]]:
    """Read only known configuration metadata and return IDs, never values or secrets."""
    refs: dict[tuple[str, str], set[str]] = {}
    config_records: list[dict[str, Any]] = []

    def add(kind: str, logical_id: Any, ref_type: str) -> None:
        if isinstance(logical_id, str) and logical_id:
            refs.setdefault((kind, logical_id), set()).add(ref_type)

    active_path = repo_root / "data" / "runtime" / "active_prompt_assets.json"
    try:
        active = json.loads(active_path.read_text(encoding="utf-8"))
        add("character_card", active.get("active_character"), "active-character")
        for value in active.get("enabled_lorebooks") or []:
            add("reality_lorebook", value, "active-lorebook")
        for value in active.get("enabled_jailbreaks") or []:
            add("reality_jailbreak", value, "active-jailbreak")
        add("dream_preset", active.get("active_dream_preset"), "active-dream-preset")
    except (OSError, UnicodeError, json.JSONDecodeError):
        pass

    # Dream settings are runtime metadata, not authored content.  Only their IDs are retained.
    for path in sorted((repo_root / "data" / "runtime" / "dreams").glob("*/settings/*.json")) if (repo_root / "data" / "runtime" / "dreams").is_dir() else []:
        try:
            settings = json.loads(path.read_text(encoding="utf-8"))
            add("dream_world", settings.get("world_layer"), "active-dream-world")
            for value in settings.get("jailbreak_presets") or []:
                add("dream_preset", value, "active-dream-preset")
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue

    config_path = repo_root / "config.yaml"
    if yaml is not None and config_path.is_file():
        try:
            config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        except Exception:
            config = {}
        for key_path, value in _walk_path_values(config):
            if not isinstance(value, str) or not _looks_like_asset_path(key_path):
                continue
            normalized = value.replace("\\", "/")
            if normalized.startswith("userdata/"):
                source = "user"
            elif normalized.startswith(("characters/", "content/", "assets/")):
                source = "legacy"
            else:
                continue
            config_records.append({
                "reference_type": ".".join(key_path), "source": source,
                "status": "canonical-reference" if source == "user" else "active-legacy-reference",
                "path": "userdata/<redacted>" if source == "user" else "legacy/<redacted>",
            })
    return refs, sorted(config_records, key=lambda item: item["reference_type"])


def _walk_path_values(value: Any, parents: tuple[str, ...] = ()) -> Iterable[tuple[tuple[str, ...], Any]]:
    if isinstance(value, dict):
        for key in sorted(value, key=str):
            yield from _walk_path_values(value[key], parents + (str(key),))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _walk_path_values(item, parents + (str(index),))
    else:
        yield parents, value


def _looks_like_asset_path(key_path: tuple[str, ...]) -> bool:
    leaf = key_path[-1].lower() if key_path else ""
    return leaf.endswith(("path", "file", "model")) or leaf in {"avatar", "sticker_pack"}


def _scan_layered_files(
    records: list[dict[str, Any]], *, category: str, user_root: Path, legacy_root: Path,
    suffixes: Iterable[str] | None, logical_id: Callable[[Path], str], canonical_kind: str,
    legacy_kind: str, repo_root: Path, userdata_root: Path, active: dict[tuple[str, str], set[str]],
    ignored_ids: set[str] | None = None,
    recursive: bool = True,
) -> None:
    # The resolver owns precedence; this inventory only materializes both sides for comparison.
    resolved = resolve_layered_files(user_root, legacy_root, logical_asset=category, suffixes=suffixes, recursive=recursive, logical_id=logical_id)
    keys = {item.logical_id for item in resolved}
    for root in (user_root, legacy_root):
        for path in _files(root, suffixes, recursive=recursive):
            keys.add(logical_id(path.relative_to(root)))
    for key in sorted(keys, key=lambda value: (value.casefold(), value)):
        if ignored_ids and key in ignored_ids:
            continue
        canonical_candidates = [p for p in _files(user_root, suffixes, recursive=recursive) if logical_id(p.relative_to(user_root)) == key]
        legacy_candidates = [p for p in _files(legacy_root, suffixes, recursive=recursive) if logical_id(p.relative_to(legacy_root)) == key]
        # Multiple files resolving to one key are an ID collision, not an arbitrary migration choice.
        canonical = canonical_candidates[0] if len(canonical_candidates) == 1 else None
        legacy = legacy_candidates[0] if len(legacy_candidates) == 1 else None
        record = _base_record(category=category, logical_id=key, key=key, canonical=canonical, legacy=legacy,
                              canonical_kind=canonical_kind, legacy_kind=legacy_kind, repo_root=repo_root,
                              userdata_root=userdata_root, legacy_root=legacy_root, active_references=active.get((category, key)))
        if len(canonical_candidates) > 1 or len(legacy_candidates) > 1:
            record.update(status="unresolved-id", recommended_action="manual-review", reason="multiple-files-normalize-to-one-id")
        else:
            _classify(record)
        records.append(record)


def _scan_worlds(
    records: list[dict[str, Any]], *, user_root: Path, legacy_root: Path, repo_root: Path,
    userdata_root: Path, active: dict[tuple[str, str], set[str]],
) -> None:
    selected = resolve_layered_directories(user_root, legacy_root, logical_asset="dream_world")
    ids = {item.logical_id for item in selected}
    for root in (user_root, legacy_root):
        ids.update(path.name for path in root.iterdir() if path.is_dir()) if root.is_dir() else None
    for world_id in sorted(ids, key=lambda value: (value.casefold(), value)):
        canonical = user_root / world_id if (user_root / world_id).is_dir() else None
        legacy = legacy_root / world_id if (legacy_root / world_id).is_dir() else None
        canonical_hash, canonical_size = _package_fingerprint(canonical)
        legacy_hash, legacy_size = _package_fingerprint(legacy)
        default = canonical.parent / "_default" if canonical is not None else (legacy.parent / "_default" if legacy is not None else None)
        record = _base_record(category="dream_world", logical_id=world_id, key=world_id, canonical=canonical, legacy=legacy,
                              canonical_kind="userdata/characters/dream/worlds", legacy_kind="characters/dream_worlds",
                              repo_root=repo_root, userdata_root=userdata_root, legacy_root=legacy_root,
                              active_references=active.get(("dream_world", world_id)))
        record.update(canonical_sha256=canonical_hash, legacy_sha256=legacy_hash, canonical_size=canonical_size, legacy_size=legacy_size)
        chosen = canonical if canonical is not None else legacy
        record["completeness"] = _package_completeness(chosen, selected_default=default)
        _classify(record, package=True)
        records.append(record)


def _seed_records(repo_root: Path, userdata_root: Path, legacy_root: Path) -> list[dict[str, Any]]:
    roots = [
        repo_root / "characters" / "default.json", repo_root / "characters" / "default_author_notes.json",
        repo_root / "characters" / "dream_postcards" / "templates", repo_root / "content" / "characters" / "default",
        repo_root / "defaults", repo_root / "examples",
    ]
    records: list[dict[str, Any]] = []
    for root in roots:
        entries = [root] if root.is_file() else _files(root)
        for path in entries:
            record = _base_record(category="public_seed", logical_id=path.name, key=_path_alias(path, repo_root=repo_root, userdata_root=userdata_root, legacy_root=legacy_root),
                                  canonical=None, legacy=path, canonical_kind="not-applicable", legacy_kind="public-seed",
                                  repo_root=repo_root, userdata_root=userdata_root, legacy_root=legacy_root)
            record.update(status="expected-public-seed", recommended_action="keep-in-release", reason="tracked-public-seed-or-template")
            records.append(record)
    fixture_root = repo_root / "characters"
    for path in _files(fixture_root, (".json",), recursive=False):
        if path.stem.startswith("memeval_"):
            record = _base_record(category="generated_fixture", logical_id=path.stem, key=path.name, canonical=None, legacy=path,
                                  canonical_kind="not-applicable", legacy_kind="generated-fixture", repo_root=repo_root,
                                  userdata_root=userdata_root, legacy_root=legacy_root)
            record.update(status="ignored-generated-fixture", recommended_action="cleanup-candidate", reason="generated-memeval-fixture")
            records.append(record)
    return records


def build_manifest(repo_root: Path, *, userdata_root: Path | None = None, legacy_root: Path | None = None) -> dict[str, Any]:
    """Return the complete dry-run result without writing anything."""
    repo_root = repo_root.resolve()
    userdata_root = (userdata_root or repo_root / "userdata").resolve()
    legacy_root = (legacy_root or repo_root).resolve()
    active, config_references = _active_references(repo_root)
    records: list[dict[str, Any]] = []
    generated_card_ids = {path.stem for path in _files(legacy_root / "characters", (".json",), recursive=False) if path.stem.startswith("memeval_")}
    _scan_layered_files(records, category="character_card", user_root=userdata_root / "characters" / "cards",
                        legacy_root=legacy_root / "characters", suffixes=_CARD_SUFFIXES,
                        logical_id=lambda relative: relative.stem, canonical_kind="userdata/characters/cards",
                        legacy_kind="characters", repo_root=repo_root, userdata_root=userdata_root, active=active,
                        ignored_ids={"default", "default_author_notes"} | generated_card_ids, recursive=False)
    _scan_layered_files(records, category="authored_character", user_root=userdata_root / "characters" / "authored",
                        legacy_root=legacy_root / "content" / "characters", suffixes=None,
                        logical_id=lambda relative: relative.as_posix(), canonical_kind="userdata/characters/authored",
                        legacy_kind="content/characters", repo_root=repo_root, userdata_root=userdata_root, active=active)
    # content/characters/default is release-owned public material, never a migration candidate.
    records[:] = [record for record in records if not (record["category"] == "authored_character" and record["logical_id"].startswith("default/"))]
    for category, name, suffix in (("reality_lorebook", "lorebooks", (".yaml", ".yml")), ("reality_jailbreak", "jailbreaks", (".json",))):
        _scan_layered_files(records, category=category, user_root=userdata_root / "characters" / "reality" / name,
                            legacy_root=legacy_root / "characters" / "reality" / name, suffixes=suffix,
                            logical_id=lambda relative: relative.stem, canonical_kind=f"userdata/characters/reality/{name}",
                            legacy_kind=f"characters/reality/{name}", repo_root=repo_root, userdata_root=userdata_root, active=active,
                            recursive=False)
    for category, filename in (("reality_lorebook_combined", "lorebook.yaml"), ("reality_jailbreak_combined", "jailbreak_entries.json")):
        user = userdata_root / "characters" / "reality" / filename
        legacy = legacy_root / "characters" / "reality" / filename
        record = _base_record(category=category, logical_id=Path(filename).stem, key=filename,
                              canonical=user if user.is_file() else None, legacy=legacy if legacy.is_file() else None,
                              canonical_kind="userdata/characters/reality", legacy_kind="characters/reality", repo_root=repo_root,
                              userdata_root=userdata_root, legacy_root=legacy_root)
        _classify(record)
        records.append(record)
    _scan_layered_files(records, category="dream_preset", user_root=userdata_root / "characters" / "dream" / "presets",
                        legacy_root=legacy_root / "characters" / "dream_presets", suffixes=(".md",),
                        logical_id=lambda relative: _dream_preset_logical_id(relative.stem), canonical_kind="userdata/characters/dream/presets",
                        legacy_kind="characters/dream_presets", repo_root=repo_root, userdata_root=userdata_root, active=active,
                        recursive=False)
    _scan_worlds(records, user_root=userdata_root / "characters" / "dream" / "worlds", legacy_root=legacy_root / "characters" / "dream_worlds",
                 repo_root=repo_root, userdata_root=userdata_root, active=active)
    _scan_layered_files(records, category="sticker", user_root=userdata_root / "assets" / "stickers",
                        legacy_root=legacy_root / "assets" / "stickers", suffixes=None,
                        logical_id=lambda relative: relative.as_posix(), canonical_kind="userdata/assets/stickers", legacy_kind="assets/stickers",
                        repo_root=repo_root, userdata_root=userdata_root, active=active)
    _scan_layered_files(records, category="avatar", user_root=userdata_root / "characters" / "reality" / "avatars",
                        legacy_root=legacy_root / "characters" / "reality" / "avatars", suffixes=(".png", ".jpg", ".jpeg", ".webp"),
                        logical_id=lambda relative: relative.stem, canonical_kind="userdata/characters/reality/avatars",
                        legacy_kind="characters/reality/avatars", repo_root=repo_root, userdata_root=userdata_root, active=active)
    records.extend(_seed_records(repo_root, userdata_root, legacy_root))
    records.sort(key=lambda item: (item["category"].casefold(), item["logical_id"].casefold(), item["relative_resource_key"].casefold()))
    counts = Counter(record["status"] for record in records)
    return {
        "schema_version": SCHEMA_VERSION,
        "read_only": True,
        "apply_supported": False,
        "summary": {
            "total_resources": len(records), "canonical_only": counts["canonical-only"], "legacy_only": counts["legacy-only"],
            "exact": counts["exact-duplicate"], "diverged": counts["diverged"],
            "invalid": counts["invalid-canonical"] + counts["invalid-legacy"],
            "incomplete": counts["incomplete-canonical-package"] + counts["incomplete-legacy-package"],
            "active_legacy_references": sum(1 for item in config_references if item["source"] == "legacy"),
            "unresolved": counts["unresolved-id"],
        },
        "config_references": config_references,
        "resources": records,
    }


def _markdown(manifest: dict[str, Any]) -> str:
    summary = manifest["summary"]
    lines = ["# Authored Root Migration Dry-Run", "", f"Schema: `{manifest['schema_version']}`", "", "## Summary", ""]
    for key in ("total_resources", "canonical_only", "legacy_only", "exact", "diverged", "invalid", "incomplete", "active_legacy_references", "unresolved"):
        lines.append(f"- {key}: {summary[key]}")
    flagged = [item for item in manifest["resources"] if item["status"] in {"diverged", "unresolved-id", "invalid-canonical", "invalid-legacy", "incomplete-canonical-package", "incomplete-legacy-package"}]
    if flagged:
        lines.extend(["", "## Needs review", "", "| Category | Logical ID | Status | Action |", "| --- | --- | --- | --- |"])
        lines.extend(f"| {item['category']} | {item['logical_id']} | {item['status']} | {item['recommended_action']} |" for item in flagged)
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only authored asset migration dry-run (no apply mode).")
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--userdata-root", type=Path)
    parser.add_argument("--legacy-root", type=Path)
    parser.add_argument("--json-output", type=Path)
    parser.add_argument("--markdown-output", type=Path)
    parser.add_argument("--fail-on-diverged", action="store_true")
    parser.add_argument("--fail-on-invalid", action="store_true")
    args = parser.parse_args(argv)
    manifest = build_manifest(args.repo_root, userdata_root=args.userdata_root, legacy_root=args.legacy_root)
    payload = json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.json_output:
        args.json_output.write_text(payload, encoding="utf-8")
    else:
        sys.stdout.write(payload)
    if args.markdown_output:
        args.markdown_output.write_text(_markdown(manifest), encoding="utf-8")
    statuses = {item["status"] for item in manifest["resources"]}
    if args.fail_on_diverged and "diverged" in statuses:
        return 2
    if args.fail_on_invalid and statuses & {"invalid-canonical", "invalid-legacy"}:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
