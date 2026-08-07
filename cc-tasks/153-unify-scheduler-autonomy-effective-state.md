# Brief 153: Unify scheduler and autonomy effective state

## Objective

Create one backend source of truth for scheduler/autonomy switches, trigger migration status, effective values, and runtime availability.

## Scope

- Add a read-only effective-state contract covering scheduler, autonomy, trigger sources, talk gate, cooldown, daily budget, and runtime state.
- Mark each trigger as migrated, maintenance-only, retired, or active.
- Distinguish configuration value, effective runtime value, override source, and restart requirement.
- Make manual trigger endpoints clearly test-only and separate from production decision paths.
- Ensure all scheduler/autonomy toggles have an executable integration test proving the switch reaches runtime behavior.
- Preserve existing config compatibility while removing ambiguous duplicate semantics from the API response.

## Non-goals

- Do not redesign the visual navigation yet.
- Do not remove legacy configuration in this task.

## Dependencies

- Requires Brief 152 because the effective state must include Self Capability overrides and protected high-risk settings.

## Acceptance

- One endpoint can explain why proactive behavior is enabled, disabled, queued, cooled down, or blocked.
- Every displayed switch has exactly one documented runtime consumer.
- Scheduler and autonomy pages can stop inferring state by combining unrelated endpoints.
- Integration tests prove at least: global off, talk off, source off, cooldown, daily budget, and Self Capability override.

## Verification

- Scheduler/autonomy integration tests with `pytest -n auto`.
- API contract/static checks.
- `git diff --check`.

## Recommended execution

- Model: `gpt-5.6-sol`
- Reasoning: `high`
- Rationale: cross-layer contract work with high regression risk.
