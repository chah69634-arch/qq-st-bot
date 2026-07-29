# Authored Root Migration Dry-Run

`scripts/authored_root_migration_dry_run.py` is the C1.3 inspection step for
an installation that may still contain private authored assets in legacy
locations. It is read-only: it never copies, moves, deletes, overwrites, or
creates an authored asset, has no `--apply` option, and creates no migration
marker.

Run it from the backend repository root:

```powershell
python scripts/authored_root_migration_dry_run.py
python scripts/authored_root_migration_dry_run.py --json-output migration.json --markdown-output migration.md
python scripts/authored_root_migration_dry_run.py --fail-on-diverged --fail-on-invalid
```

For isolated upgrade fixtures, `--repo-root`, `--userdata-root`, and
`--legacy-root` select the installation roots explicitly. Report paths are
always root aliases (`userdata/...`, `legacy/...`, `repo/...`), never ordinary
private absolute paths. The report contains IDs, sizes, hashes, validation
metadata, and field completeness only; it does not include authored text,
tokens, passwords, model contents, audio, or video.

## Resolver alignment and manifest

The JSON schema version is
`presencekit.authored-root-migration-dry-run.v1`. Each resource includes both
candidate paths and hashes, the production-equivalent effective source, active
reference types, completeness, status, recommendation, and reason. File and
package precedence is delegated to `core.authored_asset_resolver`; Dream preset
IDs use `core.asset_registry`'s stable mapping, including Chinese stems.

The scan covers cards, per-character authored files, modular and combined
Reality lorebook/jailbreak assets, Dream presets/world packages, stickers,
avatars, public seed/template roots, generated memeval residue, and known
configuration/active-asset references. Large binary files are streamed for
SHA-256 and are not decoded.

`userdata` wins the same logical file or package. A legacy-only resource is a
copy candidate only in the future migration plan; a diverged resource always
requires manual review. `bundled/` is release-owned public seed/template
material and is never a migration candidate. The old `characters/`, `content/`,
`defaults/`, and `examples/` paths remain compatibility-only readers for one
release cycle; private legacy assets are never removed by this dry-run.

## Dream packages

Each Dream world is assessed as one package. Required loader fields are
`ruleset.md`, `mes_example.md`, and `vocab.json`; loader-consumed optional
fields include lorebook, symbolic profile, HUD labels, scene labels, and meta.
The report lists required/optional missing fields, selected-root `_default`
fallback dependencies, independent materializability, and same-ID package
divergence.

An incomplete userdata package is not repaired from the legacy package. The
only safe recommendation for a same-ID conflict is an operator's future,
explicit whole-package selection after backup. `_default` and
`reality_derived` keep their loader semantics.

## Future apply prerequisites

This dry-run is evidence, not migration completion. Legacy private assets must
not be deleted merely because the canonical directory exists. A future apply
work order requires all of the following:

1. A reviewed stable manifest and explicit decisions for every diverged,
   invalid, incomplete, and unresolved entry.
2. A verified backup of both `userdata` and the legacy private asset subtrees,
   with an independently stored manifest.
3. A per-install completion marker only after a successful, reversible apply;
   this dry-run intentionally does not create one.
4. Upgrade and recovery exercises that protect `userdata/`, legacy private
   `characters/`, `content/characters/`, and `assets/stickers/` roots while
   retaining release-owned `bundled/` assets.
5. A rollback path that restores the backup and keeps legacy readers available
   until the manifest evidence is accepted.
