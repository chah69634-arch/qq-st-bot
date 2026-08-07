# Brief 157: v1 cold-start and single-user deployment audit

## Objective

Prepare v1 release readiness after the control-plane and admin-panel work is complete, focusing on first-run usability, safe defaults, recovery, and single-user server deployment.

## Scope

- Test startup from an empty data/config state.
- Verify first-run setup for model, owner, character, Embedding, auth, channels, and optional integrations.
- Audit defaults: no unsolicited speech, no external MCP connection, no hardware activation, no high-risk tool policy.
- Verify migration from v0.2.2 configuration and runtime state.
- Add a health-check/readiness checklist covering model, data paths, permissions, scheduler, autonomy, MCP, and channels.
- Document single-user deployment: local bind or HTTPS reverse proxy, token storage, backups, log rotation, restart recovery, and external MCP failure behavior.
- Test restart recovery without replaying stale proactive events.

## Non-goals

- Do not add multi-user product features.
- Do not weaken authentication because the deployment is single-user.

## Dependencies

- Requires Briefs 151 through 156.

## Acceptance

- A new user can reach a working chat from a clean install using the setup flow.
- v0.2.2 configuration either migrates cleanly or reports actionable blockers.
- Default startup is conservative and documented.
- A single-user server deployment has a documented backup and recovery procedure.
- Release checklist records known residual risks and untested optional integrations.

## Verification

- Clean-start and migration tests with `pytest -n auto`.
- Targeted frontend build/static checks.
- Manual deployment smoke test where possible.
- `git diff --check`.

## Recommended execution

- Model: `gpt-5.6-sol`
- Reasoning: `high`
- Rationale: release audit spans runtime, configuration, security, and operational recovery.
