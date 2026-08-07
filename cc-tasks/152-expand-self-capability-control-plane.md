# Brief 152: Expand Self Capability to safe management controls

## Objective

Allow the character to manage nearly all user-facing, reversible settings through Self Capability, while keeping system trust-root changes and high-risk policies explicitly user-controlled.

## Default policy

Default allowed for the character:

- Tool Loop enablement, tool presets, tool exposure, and ordinary tool execution switches.
- MCP server enable/disable for already configured servers.
- MCP allowlists and ordinary local tool policies.
- Scheduler and autonomy ordinary switches, source switches, budgets, and intervals.
- Other reversible feature switches that are already editable in the admin panel.

Default denied and never implicitly grantable:

- Passwords, API keys, tokens, or secret material.
- Administrator accounts, token profiles, or scopes.
- Importing arbitrary remote MCP URLs.
- Network proxy or server bind/listen changes.
- Data deletion or destructive retention changes.
- Disabling authentication.

High-risk tool policies, including `unrestricted` and dangerous/actuate execution modes, remain disabled by default. The admin panel may explicitly enable them; Self Capability must report the current state but must not silently elevate them.

## Scope

- Extend the capability registry with stable management capability IDs, separate from admin API scopes.
- Add a policy matrix describing default grant, agent mutability, user lock, confirmation, and high-risk status.
- Expose safe management actions through a dedicated gateway; do not expose arbitrary admin endpoints or config-file writes.
- Support optimistic revisions and audit records for every agent setting change.
- Rebuild the effective capability/tool schema after each mutation.
- Include MCP server selection by configured server name only; no arbitrary URL input.
- Add tests covering global switch, server switch, allowlist, tool preset, scheduler/autonomy settings, denied secrets, denied auth changes, denied arbitrary URL import, and high-risk policy behavior.

## Non-goals

- Do not grant admin scopes to the character.
- Do not let the character modify credentials, authentication, network binding, or delete data.
- Do not make `unrestricted` the default.

## Dependencies

- Requires Brief 151 so frozen Intiface tools do not re-enter the capability registry.

## Acceptance

- A fresh install grants safe reversible management capabilities without manual per-tool grants.
- The character can change safe settings through the gateway and the admin panel shows the audit trail.
- Every protected system change is rejected with a stable reason code.
- High-risk policies require an explicit admin-panel action and remain visible as overridden state.

## Verification

- Targeted Self Capability, tool-loop, MCP, autonomy, and auth tests with `pytest -n auto`.
- Add negative security tests before positive tests.
- `git diff --check`.

## Recommended execution

- Model: `gpt-5.6-sol`
- Reasoning: `high`
- Rationale: security-sensitive cross-module policy work; requires careful threat modeling and regression coverage.
