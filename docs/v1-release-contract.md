# v1 Release Contract

> Status: v0.2.2 preflight baseline. This document defines the product v1 release
> boundary, not a new wire protocol or architecture plan. Code wins when it conflicts
> with prose. Evidence anchors appear in backticks.

## Naming and contract rules

- Product **v1** is the release train name. The desktop wire contract remains the
  frozen **v0.1** protocol in `PresenceKit-desktop/docs/protocol-v0.md`, using
  `POST /desktop/chat` plus `/ws/desktop` (`admin/routers/chat.py`,
  `admin/admin_server.py`). No v1 WebSocket, EventBus, EventEnvelope dispatcher, or
  capability negotiation is implied or shipped.
- The current Flutter foreground chat also calls `/desktop/chat`
  (`PresenceKit-mobile/lib/services/backend_client.dart::sendChat`). `/mobile/*`
  owns activation, poll, ack, and proactive delivery (`admin/routers/mobile.py`).
- Backend owns durable business truth. Desktop and mobile own only presentation,
  local transport/configuration state, and recoverable delivery cursors.

## Stable / v1 guaranteed

| Surface | Clients | Data ownership | Failure degradation | Blocks v1 |
|---|---|---|---|---|
| Owner chat and memory pipeline | Desktop + mobile foreground; QQ optional | Backend `DataPaths`; clients do not own memory | Request error is shown; no client-side memory substitute | Yes |
| Desktop frozen v0.1 contract | Desktop | Backend message/action truth; desktop renders and acks | HTTP reply and WS delivery dedupe by `msg_id`; WS reconnects | Yes |
| Mobile proactive queue | Mobile | Backend durable queue, id/seq; mobile stores ack/seen cursor | Poll recovers missed signal delivery | Yes |
| Scoped bearer auth | Desktop + mobile + admin | Backend token registry | 401/403 fail closed; clients do not silently downgrade scopes | Yes |
| Authored asset canonical root | Backend/admin, consumed by clients | `userdata/characters/cards/` and `userdata/characters/...`; legacy reads only | Legacy `characters/` read fallback during migration | Yes |
| Atomic file writes and compatibility reads | Backend | Backend only | Preserve old data and use read fallback where implemented | Yes |

## Supported but optional

| Surface | Clients | Data ownership | Failure degradation | Blocks v1 |
|---|---|---|---|---|
| Desktop WS proactive/action delivery | Desktop | Backend queue/turn truth | Existing HTTP/chat path and desktop fallback behavior remain usable | No, after v0.1 contract tests pass |
| Mobile relay wake signal | Android mobile | Backend poll queue owns body; relay has signal only | Signal failure/reconnect falls back to poll/AlarmManager recovery | No for baseline chat; yes for claimed reliable background delivery |
| Tool loop (Path C) | Backend; desktop/mobile settings may configure it | Backend registry/config/character permissions | Global default is off; legacy probe/Path B path remains | No |
| QQ, TTS, stickers, sensors | Respective optional channel/client | Backend truth; client only captures/renders | Feature remains absent or local UI reports failure | No |

## Experimental

| Surface | Clients | Data ownership | Failure degradation | Blocks v1 |
|---|---|---|---|---|
| Android relay persistence across OEM/Doze/reboot | Android | Backend queue + mobile local cursor | Poll compensation can recover only before TTL/eviction | No for ordinary foreground use; must not be marketed as guaranteed until device evidence exists |
| MCP external tools | Backend tool loop only | External server owns tool data; backend exposes tools conditionally | Disabled by default; tool failure must not block chat | No |
| Dream Stage, Live2D/3D, hardware, Garden, Activity | Respective clients | Backend domain data; clients render/control | Feature-local error/empty state; no cross-domain fallback | No |

## Deferred post-v1

| Item | Why deferred | v1 rule |
|---|---|---|
| New desktop WebSocket protocol (`user_message`, `assistant_message`, envelopes/capabilities) | Both sides still implement v0.1 only | Do not implement or advertise it as v1 |
| Unified EventBus/EventEnvelope dispatcher | Existing entrypoints intentionally retain their own gates | Do not add dispatcher or retrofit existing flows |
| Android Keystore-backed token migration | Current credentials are in legacy `SharedPreferences` | Release blocker before public Android distribution, not an in-scope implementation |
| Expanded Live2D, 3D, MCP, hardware, Garden, Activity scope | No release-critical evidence or cross-repo contract | Keep feature scope frozen |

## Docs drift corrected by this preflight

1. Backend README card location and memory tool-loop status.
2. Desktop architecture's old event-log/diary paths and its conflation of a future WS proposal with product v1.
3. Interaction envelope document's obsolete v0.2+ promises; it is now explicitly historical/deferred.
4. Release guide's false claim that mobile has no CI and its treatment of debug-signed APKs as release-capable.
5. Mobile channel documentation now names `/desktop/chat` as the actual Flutter foreground chat endpoint.
