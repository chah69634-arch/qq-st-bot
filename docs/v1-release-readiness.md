# v1 Release Readiness

> Status: preflight checklist, not release approval. `blocking` means no public
> v1 release claim until evidence is recorded; it does not authorize unrelated
> implementation.

> **PresenceKit v1.0.0 is the first supported update baseline. Preview v0.x
> installations must migrate through backup and fresh installation.**

## Blocking / non-blocking

| Priority | Item | Current evidence | Exit evidence |
|---|---|---|---|
| Blocking | Android production signing | `android/app/build.gradle.kts` falls back to debug signing when `android/key.properties` is absent | Keystore custody/runbook, signed APK verification, and upgrade from prior signed build |
| Blocking | Android token security and migration | `BackendSecurityPolicy.kt` reads admin/relay tokens from `SharedPreferences`; mobile architecture says Keystore is not integrated | Encrypted/Keystore store, one-time migration, rollback/reauth behavior, no plaintext residue test |
| Blocking | Backend update transaction and data recovery | v1+ updater creates a program snapshot and preserves protected roots; dependency sync still occurs after replacement | Release-candidate upgrade/failure/restore rehearsal and backup-manifest evidence |
| Blocking | Authored-root migration recovery evidence | C1.3 is read-only and C1.1/C1.2 preserve canonical writer/read layering | Reviewed C1.3 results and manual resolution of legacy-only/diverged assets before relying on fallback |
| Blocking | Data schema/version policy | `data/layout_version.json` establishes v1 baseline/schema 1; future schema changes need an explicit supported forward path | Version matrix and forward-migration evidence for each later schema change |
| Blocking for reliable background claim | Relay real-device recovery | Queue has 24h / 500 cap (`channels/mobile.py`); relay publisher retries/logs but has no operator alert | Real-device matrix: background, Doze, process kill, reboot, relay loss/reconnect; TTL/cap eviction and alert evidence |
| Blocking | Path B observation and deletion decision | Path B remains in `core/pipeline.py`; Path C is optional and default-off | Metrics/log review window, zero-required-use or bounded exceptions, approved removal criteria and rollback plan |
| Blocking | Three-repo protocol fixtures | Current desktop v0.1 is cross-repo prose/code; mobile foreground chat uses shared `/desktop/chat` | Versioned fixtures for v0.1 WS + HTTP correlation + mobile poll/ack, compatibility matrix executed against all three heads |
| Blocking | Install/upgrade/downgrade/recovery | v1-only fixture covers baseline, forward update, repeat, restore, and refusal paths | Release-candidate rehearsal across the three repos and documented operator recovery evidence |
| Non-blocking | Future WS v1/envelope/EventBus | Not implemented (`docs/protocol-v0.md`, `docs/interaction-event-model.md`) | None: explicitly post-v1 |
| Non-blocking | Live2D, 3D, MCP, hardware, Garden, Activity expansion | Out of preflight scope | Feature-specific work orders only |

## v1 update baseline

The retired v0.2.2 bridge is not a release path. Preview v0.x carries no
automatic-upgrade or data-continuity promise: users back up `data/`, `userdata/`
and the local configuration/secrets files, install v1 into a new directory, and
copy only those protected items. Old program trees (`characters/`, `content/`,
`defaults/`, `examples/`, `core/`, `scripts/`, `.venv/`) are not copied. C1.3
dry-run results marked legacy-only, diverged, invalid, incomplete, or unresolved
require manual review.

On the first successful v1 initialization, `data/layout_version.json` records
the product baseline (`v1`), data layout schema, and first v1 initialized
version. It contains no user content or credentials and is not a generic
migration framework. The v1+ updater accepts only a source at least `v1.0.0`,
an equal-or-newer target, and a marker schema it supports; preview/unknown
sources, future schemas, and downgrades fail before program replacement.

The isolated fixture matrix covers fresh marker creation; v1.0.0→v1.0.1 and
v1.0.0→v1.1.0 updates; protected-root preservation; bundled replacement;
idempotence; explicit restore; and refusal for pre-v1, unknown, future-schema,
and downgrade sources. It uses only `tmp_path` and does not touch real data.

## Required compatibility matrix

Record exact build hashes and fixture result for each release candidate.

| Backend | Desktop | Mobile | Required assertion |
|---|---|---|---|
| Candidate | Candidate | Candidate | Auth, `/desktop/chat`, v0.1 WS hello/message/action/ack, mobile poll/ack |
| Candidate | Previous supported | Previous supported | No wire/schema regression or explicitly blocked upgrade |
| Previous supported | Candidate | Candidate | Clear incompatibility refusal or supported behavior; never silent corruption |
| Candidate | N/A | Fresh Android install | Token setup, chat, poll delivery, no private build-time configuration |

The mobile `/mobile/chat` endpoint must not be inserted into this matrix unless a
separate versioned implementation changes `BackendClient.sendChat()`.

## Release validation sequence

1. Freeze the three commits and generate protocol fixtures from the current v0.1
   contract; run backend, desktop, and mobile CI/build checks.
2. Exercise fresh v1 install, same-version reinstall, and v1 forward update on
   isolated data copies. Verify marker, backup, restart, auth, character-card
   layered reads, and mobile queue recovery.
3. Confirm preview v0.x is refused by updater and the backup/fresh-install
   migration procedure is available; test v1 restore rather than downgrade.
4. Complete Android signed-install and relay device matrix before describing
   background delivery as reliable.
5. Review Path B observation logs over an agreed window before any deletion brief.
6. Publish only after the compatibility matrix and artifacts/sha256 records are
   attached to the release decision.
