# Brief 151: Freeze Intiface as an opt-in reserve capability

## Objective

Freeze the Intiface / hardware-control line as a dormant reserve feature. It must not influence normal prompts, Tool Loop exposure, Self Capability discovery, autonomy tool selection, or default startup behavior.

## Scope

- Remove `toy_vibrate`, `toy_stop`, `toy_pattern`, and `toy_job_status` from every default tool exposure path.
- Keep the implementation and registry entries available for explicit future opt-in.
- Make the default state visibly disabled in the admin panel.
- Ensure `toy_job_status` cannot be repeatedly selected merely because the `info` category is enabled.
- Preserve owner-only and hardware safety gates.
- Add regression tests for default schema exposure, Self Capability listing, autonomy tool listing, and direct dispatch rejection when the feature is frozen.

## Non-goals

- Do not delete Intiface code or protocol support.
- Do not change MCP behavior.
- Do not loosen hardware safety gates.

## Dependencies

None. This is the first task.

## Acceptance

- A default installation exposes none of the four hardware tools to normal chat, autonomy, or Self Capability.
- Explicit opt-in is required before any hardware tool can be registered or executed.
- `toy_job_status` is not present in the normal `info` default set.
- Existing hardware tests remain valid or are updated to describe the dormant opt-in contract.

## Verification

- Targeted hardware/tool-dispatcher tests with `pytest -n auto`.
- `git diff --check`.

## Recommended execution

- Model: `gpt-5.6-luna`
- Reasoning: `medium`
- Rationale: bounded registry/config/test change; no broad architectural redesign.
