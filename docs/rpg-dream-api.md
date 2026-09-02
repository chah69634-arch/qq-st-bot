# RPG Dream API v1

RPG Dream is a backend-only Dream mode. Clients discover support from
`GET /dream/capabilities`; they must not read runtime files or infer fields from
WebSocket frames. Desktop remains open until its client work order consumes
this contract, and mobile has no v1 UI consumer.

All RPG endpoints use the `activity` scope except
`GET /observability/dream-rpg`, which uses `state.read`.

The REST surface is `POST /dream/enter` with `dream_mode=rpg` and an existing
`script_id`, `GET /dream/rpg/state`, `POST /dream/rpg/turn`,
`GET /dream/rpg/transcript`, `POST /dream/rpg/corrections`,
`GET /dream/archive`, `GET /dream/archive/{dream_id}`,
`GET /observability/dream-rpg`, and the existing `POST /dream/exit`.

Turn requests contain `dream_id`, opaque `request_id`, `lane` (`character` or
`kp`), `message`, and `expected_scene_revision`. A repeated request ID with
the same digest returns the original response; a different digest returns
`RPG_IDEMPOTENCY_CONFLICT`. Only one round is in flight per session, and a
revision mismatch returns `RPG_REVISION_CONFLICT`.

Responses expose only player-visible `character`, `kp`, and `shared` entries.
KP prompts, hidden facts, dice seed/faces/DC, unselected branches, model output,
and absolute paths are never returned. A valid character `<C>intent</C>` marker
is removed before display and can trigger at most one bounded check subcycle.

Stable errors use `{"detail":{"code":"...","message":"...","retryable":false}}`.
Important codes are `RPG_NOT_ACTIVE`, `RPG_DREAM_ID_MISMATCH`,
`RPG_ENDPOINT_REQUIRED`, `RPG_ROUND_BUSY`, `RPG_IDEMPOTENCY_CONFLICT`,
`RPG_REVISION_CONFLICT`, `RPG_INVALID_LANE`, `RPG_KP_OUTPUT_INVALID`,
`RPG_CHARACTER_GENERATION_FAILED`, and `RPG_SESSION_UNCERTAIN`.
