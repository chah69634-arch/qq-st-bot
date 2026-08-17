# Memory Event Baseline

This document records the compatibility boundary before the Memory Event work
series. It is intentionally descriptive: it creates no runtime state, event
identifier, storage, prompt layer, or migration.

The executable fixture is `tests/fixtures/memory_event_baseline.json`; its
regression test is `tests/test_memory_event_baseline.py`.

## Preserved Chain

`capture_turn()` remains the common legacy writer for a normal owner turn. Its
canonical `turn_id` is stored with the paired short-term entries and event-log
entries. Mid-term and episodic entries may later retain that value as
`source_turn_id`; this baseline does not force consolidation.

`Pipeline.fetch_context()` continues to expose the existing context keys and
writes diagnostic-only `recall_trace` records. The trace is an audit output,
never prompt input.

Transport identifiers are not memory identifiers. QQ inbound identifiers stay
transport-local. For desktop and mobile assistant delivery, the existing turn
sink projects the canonical post-process `turn_id` as the outgoing `msg_id`
when one is available.

## Boundaries Captured

The fixture names normal QQ/desktop/mobile owner chat, an assistant-only
scheduler turn, image/file-bearing input, and the same owner under two
characters. It also records Dream, Stage, web echo, and coplay as isolation
cases. These names are baseline cases, not new runtime event kinds.

While later Memory Event work is disabled, the golden assertions require the
same short-term shape, event-log search result shape, `fetch_context()` keys,
recall-trace keys, and character isolation. Any intentional change must update
this document, the fixture, and its regression assertion together.
