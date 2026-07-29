# v1 Release Readiness

> Status: preflight checklist, not release approval. `blocking` means no public v1
> release claim until evidence is recorded; it does not authorize implementation in
> this documentation-only work order.

## Blocking / non-blocking

| Priority | Item | Current evidence | Exit evidence |
|---|---|---|---|
| Blocking | Android production signing | `android/app/build.gradle.kts` falls back to debug signing when `android/key.properties` is absent | Keystore custody/runbook, signed APK verification, and upgrade from prior signed build |
| Blocking | Android token security and migration | `BackendSecurityPolicy.kt` reads admin/relay tokens from `SharedPreferences`; mobile architecture says Keystore is not integrated | Encrypted/Keystore store, one-time migration, rollback/reauth behavior, no plaintext residue test |
| Blocking | Backend update transaction and data recovery | `scripts/update_release.py` rolls back copied program files, but dependency sync happens after replacement; data compatibility is not a release transaction | Backup manifest, schema/version inventory, upgrade failure recovery, documented rollback/restore drill |
| Blocking | Data schema/version policy | Versions exist only per artifact (for example hidden state/perception/wake bridge); no release-wide data schema ledger | Version matrix, forward migration, downgrade policy, and fresh data/create/restore tests |
| Blocking for reliable background claim | Relay real-device recovery | Queue has 24h / 500 cap (`channels/mobile.py`); relay publisher retries/logs but has no operator alert | Real-device matrix: background, Doze, process kill, reboot, relay loss/reconnect; TTL/cap eviction and alert evidence |
| Blocking | Path B observation and deletion decision | Path B remains in `core/pipeline.py`; Path C is optional and default-off | Metrics/log review window, zero-required-use or bounded exceptions, approved removal criteria and rollback plan |
| Blocking | Three-repo protocol fixtures | Current desktop v0.1 is cross-repo prose/code; mobile foreground chat uses shared `/desktop/chat` | Versioned fixtures for v0.1 WS + HTTP correlation + mobile poll/ack, compatibility matrix executed against all three heads |
| Blocking | Install/upgrade/downgrade/recovery | Current docs describe pieces, not an executed matrix | Fresh install, same-version reinstall, upgrade, downgrade refusal/restore, damaged queue/data recovery across all three repos |
| Non-blocking | Future WS v1/envelope/EventBus | Not implemented (`docs/protocol-v0.md`, `docs/interaction-event-model.md`) | None: explicitly post-v1 |
| Non-blocking | Live2D, 3D, MCP, hardware, Garden, Activity expansion | Out of preflight scope | Feature-specific work orders only |

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
2. Exercise fresh install then normal upgrade on isolated data copies. Verify backup,
   restart, auth, character-card migration fallback, chat, and mobile queue recovery.
3. Exercise downgrade only against a documented compatible case; verify refusal and
   manual restore path for incompatible schemas.
4. Complete Android signed-install and relay device matrix before describing
   background delivery as reliable.
5. Review Path B observation logs over an agreed window before any deletion brief.
6. Publish only after the compatibility matrix and artifacts/sha256 records are
   attached to the release decision.

## Recommended follow-up work order order

1. Release data safety: schema ledger, backup manifest, upgrade/rollback/recovery drill.
2. Android secret-storage migration and signed-release supply-chain runbook.
3. Cross-repo v0.1 fixtures and compatibility matrix automation.
4. Android relay device/reboot/TTL/capacity/alert observability validation.
5. Path B observation report, removal criteria, then a separately approved deletion brief.
6. Only after v1 ships: evaluate a new WS protocol or unified event model as separate design work.

## Preflight evidence anchors

- `admin/routers/chat.py` defines the authenticated `/desktop/chat` owner-chat route.
- `PresenceKit-mobile/lib/services/backend_client.dart::sendChat` uses `/desktop/chat`.
- `admin/routers/mobile.py` defines activation/poll/ack/push, and `channels/mobile.py`
  persists the mobile queue with 24h/500 pruning.
- `channels/relay_publisher.py` retries signal publishing up to three times and logs
  failure; it has no durable operator alert path.
- `PresenceKit-desktop/docs/protocol-v0.md` is the frozen desktop v0.1 authority.
