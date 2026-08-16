# External Companion contract

This is the cross-repository contract frozen by Brief 192 for the independent
PresenceKit Companion adapter. Brief 193 implements the runtime route in this
repository; the Companion repository remains a fixture-only consumer.

## Ownership

The external adapter may submit a bounded opportunity or a player-entered phone
message. PresenceKit remains authoritative for the owner, active character,
channel, origin, trust, reply text, relationship, memory, and any tool policy.
The adapter body cannot choose those values and cannot request a memory write.

The game opportunity lane is non-user-authored:

```text
source = stardew-companion
activity_kind = cozy_game
user_authored = false
provenance.origin = external_companion
retention_policy = ephemeral | bounded_observation
```

The phone lane carries the text entered by the player, but the server maps it to
the fixed owner-input path. It is not a game fact and must not be represented
as one.

## Frozen surface

| item | value |
|---|---|
| request | `POST /integrations/companion/events` |
| scope | `companion.write` |
| contract | `presencekit-external-companion-v1` |
| idempotency | opaque `session_id + event_id` |
| reply | optional bounded `reply` object with server provenance |
| storage | no direct memory writer; bounded ingress receipt only after implementation |
| current state | `current` for the PresenceKit HTTP boundary; cross-process E2E remains `open` |

## Runtime behavior

`POST /integrations/companion/events` requires the dedicated `companion.write`
scope. The body is strict, bounded to 16 KiB, and cannot declare owner,
character, channel, origin, trust, memory, tool, filesystem, or network
authority. The server resolves and freezes owner ID and active character once
per turn.

`opportunity` is sent through `receive_perceive_event()` as a low-trust,
non-user-authored stimulus. Dream guard yields `deferred`, proactive-off yields
`muted`, and generated turns use a zero-write envelope, zero tools, and no
channel fanout. `phone_message` uses the fixed owner-input path with
`user_authored=true`, `companion_phone_input` provenance, empty tool exposure,
and normal owner memory policy, but its reply also returns only over HTTP.

The durable receipt identity is `caller + session_id + event_id`. A receipt is
reserved as `running` before execution; completed duplicates return metadata
only and never replay reply text. A running receipt left by a previous process
is treated as uncertain and returns `503 COMPANION_TEMPORARILY_UNAVAILABLE`.
Events older than five minutes expire without entering the pipeline. Session
switches require a strictly newer `created_at`; old sessions return `409`.

`GET /observability/companion-events` requires `state.read` and returns only
hashed opaque IDs, caller labels, statuses, counts, timings, session update
times, and prune metadata. It never returns token values, request content,
summary, reply text, owner IDs, character text, or filesystem paths. There is
no companion-specific user setting: this is a fixed server capability.

The companion repository keeps the corresponding sanitized request/reply/error
fixtures under its own `protocol/presencekit-external-companion-v1/` directory.
Those fixtures contain no token, account, private character text, or local
filesystem path.

## Event-model boundary

This contract reuses the existing low-trust stimulus gate for opportunities and
the existing message path for player phone input. It does not add a new
`kind=activity`, `kind=mcp`, unified EventEnvelope, dispatcher, or EventBus.
External replies leave through the normal assistant turn/channel fanout and are
not re-ingested as a new stimulus.
