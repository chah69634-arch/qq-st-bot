# Brief 155: Reorganize the admin panel around user workflows

## Objective

Replace the module-grown navigation with a task-oriented information architecture and add a real control-center landing page.

## Proposed top-level areas

- Home / Overview
- First-run setup
- Conversation and character
- Proactive behavior
- Tools and external connections
- Memory and growth
- Channels and devices
- Observability and troubleshooting
- Security and accounts
- Advanced settings

## Scope

- Add a navigation/overview page as the default authenticated page.
- Group existing pages by user task, without removing existing routes.
- Add short purpose text and configuration-source/effective-scope hints to each settings page.
- Make related settings cross-link to their canonical edit page.
- Keep read-only observability visually distinct from editable settings.
- Preserve deep links, active-page persistence, mobile navigation, and existing permission checks.

## Dependencies

- Requires Brief 153 for the effective-state contract.
- Requires Brief 154 so all new shell and dynamic text follows the fixed i18n behavior.

## Acceptance

- A new user can find where to enable/disable a feature from the overview without knowing internal module names.
- Existing deep links continue to work.
- No setting is presented as editable on a read-only page.
- Navigation labels and page descriptions work in both supported languages.

## Verification

- Admin static/UI tests, route smoke tests, and manual viewport checks.
- Frontend build if the client/static pipeline requires it.
- `git diff --check`.

## Recommended execution

- Model: `gpt-5.6-terra`
- Reasoning: `medium`
- Rationale: primarily information architecture and shell composition after backend contracts are stable.
