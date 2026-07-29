# Backend Upgrade and Recovery

## Compatibility policy

v1 is the long-term compatibility baseline.

| Installed source | Update policy |
|---|---|
| Fresh v1 install | Supported |
| v0.2.2 | Direct bridge to v1.0.0 is supported |
| Earlier than v0.2.2 or unrecognised | Refuse; first upgrade to v0.2.2 or use a manual backup restore |
| v1 and later | Only normal forward updates; every data-layout change needs a continuous forward migration |
| Downgrade | Unsupported; restore the pre-upgrade backup instead |

This is deliberately not a universal historical migration system. The updater
does not infer an unknown legacy layout or silently copy private authored data.

## v0.2.2 to v1 bridge

For the one supported direct bridge, the updater first creates the complete
pre-update snapshot `_update_backup_v0.2.2/`. It then overlays verified program
files, adds the release-owned `bundled/` tree, and removes only the enumerated
former public files. It leaves these unchanged:

- `userdata/` authored assets
- `data/` runtime and memory state
- `config.yaml`, `config.local.yaml`, `secrets.local.yaml`, `.venv/`, and `tools/uv.exe`
- unknown private files in legacy roots or elsewhere in the installation

After the released v1 bundled assets pass the existing compatibility-read
bootstrap check, the updater atomically writes the installation metadata marker
`_presencekit_upgrade/v0.2.2_to_v1_bridge_completed`. The marker means only
that this named bridge completed. It carries no generic schema or migration
engine semantics.

## Failure and retry

- If creating the pre-update backup fails, the updater stops before program
  replacement.
- If program copying fails, it reports the failure and restores program files
  already replaced during that attempt from the snapshot.
- If the bridge compatibility/bootstrap check fails, no completion marker is
  written. The preserved v0.2.2 snapshot lets the same v1.0.0 update retry
  safely.
- A repeated completed bridge is idempotent and preserves the original v0.2.2
  snapshot.
- Dependency synchronization happens after the program overlay. A dependency
  failure does **not** claim automatic rollback; inspect the terminal output,
  repair the environment, retry, or restore the snapshot.

## Manual recovery

Stop PresenceKit first. From the installation root, restore the updater-created
snapshot explicitly:

```bash
python scripts/update_release.py --restore-backup _update_backup_v0.2.2
```

This restores the complete pre-update snapshot and is the formal route for an
unsupported downgrade or an unrecoverable failed upgrade. Save any files newly
created after the upgrade before doing so, because snapshot restoration returns
the installation to its old state.

## Verification boundary

The automated fixture uses only synthetic assets, memory, config, and fake
credentials. It verifies fresh v1 installation, bridge preservation, public
cleanup, retry/idempotence, forced failure, and restore behavior. It does not
replace a release-candidate rehearsal on a copied real installation; that
manual exercise remains required before public v1 approval.
