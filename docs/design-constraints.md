# Design constraints: remote owner turns and diary mirror

This page records the Brief 171 additions to the repository's design rules;
the broader design authority remains [`DESIGN.md`](../DESIGN.md).

- The versioned owner-turn API is an adapter over the existing Reality
  pipeline, conversation gate, frozen character scope, and turn sink. It does
  not create a second pipeline, memory writer, or event bus.
- Caller identity, owner scope, provenance, live origin, and tool capability
  come from server-side token/profile configuration. Request JSON cannot
  override them.
- `deployment.mode=remote_server` fails closed for server-local OS commands,
  filesystem browsing, legacy exit signaling, and desktop file fallbacks.
  Client actions require the existing desktop WS acknowledgement.
- The Obsidian diary mirror accepts only bounded dated Markdown entries and
  metadata. It is runtime integration state, separate from the character
  inner-diary API, and tombstones do not physically delete source or mirror
  files.
