# Brief 156: Add global defaults, overrides, and edit links to the overview

## Objective

Make the new control-center page explain the complete global configuration state at a glance.

## Scope

Display, per feature:

- Default value.
- Current configured value.
- Effective runtime value.
- Override source: default, config, character card, user grant, agent override, or runtime gate.
- Runtime status and blocking reason.
- Hot-reload versus restart requirement.
- Direct link to the canonical edit page.

The overview must include at least Tool Loop, MCP, Self Capability, autonomy, scheduler, channels, model routing, Embedding, TTS, and hardware/Intiface frozen state.

## Dependencies

- Requires Brief 153 effective-state backend contract.
- Requires Brief 155 control-center navigation.

## Acceptance

- The overview never guesses effective state from unrelated UI fields.
- Every row has a source and edit destination, or is explicitly read-only.
- Contradictory values show an explanation rather than silently choosing one.
- Frozen Intiface is visibly dormant and not confused with MCP.

## Verification

- API/UI contract tests for default, override, disabled, unavailable, and restart-required states.
- `git diff --check`.

## Recommended execution

- Model: `gpt-5.6-sol`
- Reasoning: `high`
- Rationale: depends on the new effective-state model and must avoid misleading operational summaries.
