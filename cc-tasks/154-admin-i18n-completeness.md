# Brief 154: Make admin-panel language switching complete

## Objective

Fix the partial Chinese/English switch so every visible admin-panel label, dynamic status, toast, table heading, and page fragment updates without requiring a full browser reload.

## Scope

- Replace hard-coded dynamic UI strings with translation keys and `t()` calls.
- Add missing `data-i18n`, placeholder, and aria-label attributes in page fragments.
- Ensure dynamic tables, badges, scheduler trigger labels, MCP states, and error messages are translated.
- Make language switching re-render active dynamic data and invalidate/reload fragments consistently.
- Audit static asset and fragment versioning so stale cached fragments cannot preserve the previous language.
- Add a test that loads every page fragment in both languages and detects untranslated fallback text or mixed-language fixed labels.

## Non-goals

- Do not translate user-authored content, logs, prompts, tool descriptions, or memory text.
- Do not change backend semantics.

## Dependencies

- Can start after Brief 153; should be completed before the navigation redesign so new UI uses the corrected i18n pattern.

## Acceptance

- Switching language updates the current page in place.
- Navigating to another page does not restore stale-language shell text.
- No known page contains a mixture caused by hard-coded UI labels.
- Cache-busting versions follow the repository rules.

## Verification

- Existing admin i18n/static asset tests plus new page-fragment coverage.
- `git diff --check`.

## Recommended execution

- Model: `gpt-5.6-terra`
- Reasoning: `high`
- Rationale: broad frontend consistency pass; needs careful handling of dynamic rendering but not a new backend architecture.
