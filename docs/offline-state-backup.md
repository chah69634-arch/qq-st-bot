# Offline Private-State Backup

`scripts/update_release.py` creates an updater rollback copy of **program
files**.  It intentionally preserves local state and is not a private-state
backup.  `backup-state` is a separate offline snapshot for the local private
state described below.

## Scope and safety boundary

Create a snapshot only after PresenceKit has been stopped.  The command checks
the lifecycle PID marker and process state before reading any source file.  A
running service or an indeterminate result fails closed; it never stops a
process, retries around concurrent writes, or performs an online backup.
The current non-sensitive decision is also available to `state.read` tokens at
`GET /observability/backup-service-state`; it returns only `offline`,
`running`, or `unknown`.

The current protection inventory (version 1) includes:

- `data/`, except clearly derived/forensic caches: vector indexes and SQLite
  sidecars, memory indexes, image cache, inbox, ordinary logs, debug output,
  pending perception files, opt-in LLM request logs, and the ephemeral service
  PID marker;
- `userdata/` when it exists;
- required `config.yaml`, plus optional `config.local.yaml` and
  `secrets.local.yaml` when present;
- legacy private authored-asset subtrees still supported for compatibility:
  private cards/notes, Reality/Dream assets, stickers, and non-example
  per-character content.  Public `bundled/`, defaults, examples, source code,
  virtual environments, build output, release-updater backups, and ordinary
  logs are not copied.

The inventory is centralized in `core.backup_state.PROTECTION_ROOTS`.  An
audited future private root must be classified there; a known unclassified root
causes creation to fail rather than being omitted.

## Create and verify

Snapshots must be placed outside the installation directory, including its
`data/` and `userdata/` roots.  The output must not already exist.

```powershell
python main.py backup-state create --output <protected-volume>\presencekit-snapshot --protection-mode protected_volume
python main.py backup-state verify <protected-volume>\presencekit-snapshot
```

Use `--json` for a small structured result and `--quiet` to suppress a success
message.  Results never print config, token, secret, memory, or manifest-file
contents.

The sole first-release mode is `protected_volume`: it is an unencrypted
directory snapshot and the operator explicitly asserts that its destination is
a protected volume.  It is **not** described as encrypted.  Portable/offsite
archives require audited standard encryption before this command will support
them.  The current dependency set has no approved archive-encryption library,
so this work intentionally does not invent cryptography or accept passwords on
the command line.  A future portable mode should add a reviewed, maintained
dependency with hidden-input or OS secret-store key handling.

## Manifest and verification

Every snapshot has `manifest.json` and a sibling `manifest.sha256` integrity
check.  The versioned manifest contains product version, data-layout marker
fields, timestamp, backup id, protection mode, protection-root inventory,
optional absent files, and per-file relative path, size, SHA-256, and root id.
It never stores installation paths, configuration contents, memories, tokens,
or secrets.  SQLite files are copied only while stopped; WAL/SHM files that are
not explicitly excluded are included as ordinary declared files rather than
being guessed at or deleted.

`verify` validates the manifest/checksum, supported schema, layout metadata,
root inventory, required config entry, every declared size/hash, safe relative
paths, reparse points, readability, and unexpected files.  It validates backup
integrity only.

## Not supported

This command does not restore in place, modify live data, stop/start the
service, back up while it runs, upload to cloud storage, copy to a network
drive, or automatically delete old snapshots.  Retention is deliberately left
separate until restore and operator storage policies are designed and tested.

## Restore and recovery drill

Restore verifies the source snapshot first and publishes only to a nonexistent
or completely empty directory outside the live installation and snapshot:

```powershell
python main.py backup-state restore <snapshot> --target <new-empty-directory>
```

It rejects unsafe/absolute paths, reparse points, Windows case collisions,
ADS/device names, excessive path lengths, file-count/size limits, and hash
mismatches. Every restored file is re-hashed. The default read-only startup
check parses config/auth, loads active character/assets and Lore/Pipeline, and
parses JSON state without starting services. A no-outbound guard blocks LLM,
MCP, QQ, channel fanout, scheduler, web/search/weather, and hardware calls.
No queue is consumed and no runtime memory/state is written.

The restored directory receives a secret-safe
`.presencekit-recovery/recovery-report.json`. `--no-startup-check` is only for
diagnostics, not recommended recovery. Final cutover remains manual; there is
no automatic rollback, online restore, or implicit cross-version migration.
