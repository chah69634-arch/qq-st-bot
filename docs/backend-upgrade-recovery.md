# Backend Upgrade and Recovery

> **PresenceKit v1.0.0 is the first supported update baseline. Preview v0.x
> installations must migrate through backup and fresh installation.**

## Compatibility policy

| Installed source | Update policy |
|---|---|
| v0.x preview / unrecognised installation | Automatic update is unsupported. Back up private state, install v1 into a new directory, then copy the protected data. |
| v1.0.0 and later with supported layout marker | Supported continuous forward update with a complete pre-update backup. |
| Source layout schema newer than this program | Refuse before writes; use a compatible program version or restore a backup. |
| Downgrade | Unsupported; restore the updater-created pre-update backup. |

This is deliberately not a historical migration engine. C1.1 writer gates,
C1.2 layered reads, C1.3 inspection, and C1.4 `bundled/` remain normal v1
behavior; they do not make a preview installation eligible for automatic
conversion.

## Moving from preview v0.x to v1

1. Stop PresenceKit and make independent copies of `data/`, `userdata/`,
   `config.yaml`, `config.local.yaml` (if present), and `secrets.local.yaml`
   (if present).
2. Install v1 into a **new empty directory**. Do not overlay the v0.x program
   directory.
3. Copy only those protected roots/files into the new v1 directory. Do not copy
   old program assets or environments: `characters/`, `content/`, `defaults/`,
   `examples/`, `core/`, `scripts/`, or `.venv/`.
4. Before relying on legacy authored fallback, run the read-only C1.3 check:

   ```bash
   python scripts/authored_root_migration_dry_run.py --fail-on-diverged --fail-on-invalid
   ```

   `legacy-only`, `diverged`, `invalid`, `incomplete`, or `unresolved` results
   require manual review. The command never copies, overwrites, or deletes
   authored assets.
5. Start v1 normally. Once configuration, authentication, character loading,
   and Pipeline initialization succeed, v1 writes `data/layout_version.json`.
   It records only `product_baseline: "v1"`, the data layout schema version,
   and the first v1 version that initialized that data directory.

## v1+ update contract

The unpacked-package updater accepts only a source `VERSION` at or above
`v1.0.0`, a non-downgrade target at or above `v1.0.0`, and a readable
`data/layout_version.json` whose `product_baseline` is `v1` and whose schema is
supported by the running updater. It fails before program replacement for a
preview source, an unknown installation, an absent/invalid marker, a newer
schema, or a downgrade.

For a valid source it verifies the downloaded ZIP and SHA-256, creates one
complete `_update_backup_<source-version>/` snapshot, overlays only program
files (including the release-owned `bundled/` tree), and leaves `data/`,
`userdata/`, `config.yaml`, `config.local.yaml`, `secrets.local.yaml`, `.venv/`,
and `tools/uv.exe` untouched. A repeated same-version update is idempotent.
Dependency synchronization happens after the overlay; a dependency failure
does not claim automatic rollback.

## Recovery

Stop PresenceKit first. From the v1 installation root, restore the updater-made
snapshot explicitly:

```bash
python scripts/update_release.py --restore-backup _update_backup_<source-version>
```

Save any post-update files that must survive before restoring. Restoration is
the only supported downgrade/recovery route; it returns the installation to the
complete snapshot and does not infer a cross-version data migration.
