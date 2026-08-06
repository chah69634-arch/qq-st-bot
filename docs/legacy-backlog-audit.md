# Legacy Backlog Audit

> Living audit log for older product decisions and bug notes. Append new batches
> rather than treating this file as an implementation plan. Code is the release
> truth; a status of "implemented" does not imply device or release acceptance.

## Status legend

| Status | Meaning |
|---|---|
| Implemented | The requested capability, or a clearly stronger compatible replacement, is on the active path. |
| Partial | A useful part exists, but the stated contract or an operational guarantee is missing. |
| Deferred | Not an active implementation target; it needs a product/protocol decision or is superseded. |
| Open | No suitable implementation was found. |

## Batch: interaction, memory, delivery, and operations

### Interaction

| Item | Status | Audit result | Follow-up |
|---|---|---|---|
| A. Time-asymmetric response tone | Partial | Prompt layer `2.5_time`, a night-sensitive style hint, and late-night sensor events exist. There is no structured time-band-to-expression policy. `perception_block` is reserved for pending desktop perception and cross-channel continuation. | If implemented, add a separately observable prompt layer instead of overloading `perception_block`. |
| B. Gradual "miss you" after absence | Partial | Presence attribution, silence ratio, and `presence_nag` exist. `presence_nag` is a guarded desktop popup (default 60 minutes, negative mood, QUIET state, cooldown), not a 15 min/1 h/several-hours/day escalation curve. | Build a dedicated proposer so DND, sleep guard, Dream guard, cooldown, locks, and mobile delivery stay intact. |
| High-pressure-window notes | Open | Author-note selection currently weighs recency and underrepresented traits only. No note type or selector combines emotion, relationship state, continuity, and low probability. | Define consent, state inputs, frequency cap, exit conditions, and observability before adding it. |

### Prompt/tool architecture

| Item | Status | Audit result | Follow-up |
|---|---|---|---|
| Asymmetric probe | Implemented | Path A probes only `info` and `desktop`; memory tools are exposed through owner-only, function-calling Path C tool loop. Path C skips the general probe. | Re-evaluate by latency, cost, tool-completion, and regression evidence, not by code shape alone. |
| Query-sensitive prompt trimming | Partial | Current trim order retains episodic memory later than mid-term memory. Episodic selection is relevance-aware, but global prompt trimming is still fixed layer priority. | Keep deferred pending an eval that shows fixed trimming is the bottleneck. |
| HTTP to SSE/WS and channel registry | Implemented / partial | Authenticated desktop and device WebSockets, streaming, turn-sink fanout, and channel registry are active. Mobile has a durable poll/ack queue. The registry is channel-level, not a multi-client session registry. | Do not replace WS with SSE merely for parity. Multi-client delivery needs a versioned session/client identity design. |
| Apple Watch preparation | Deferred | Backend accepts watch signals with a narrow scope. No iOS host or WatchConnectivity client exists here. | Design in the iOS/mobile scope after a versioned delivery contract is approved. |

### Memory and recall

| Item | Status | Audit result | Follow-up |
|---|---|---|---|
| Importance/significance score | Partial | There is no independent `importance: 1-10`; `strength` is LLM-initialized and rule-corrected, with `is_core`. | Add only if its meaning is distinct from strength/retention; otherwise it duplicates the existing score. |
| Semantic recall | Implemented | sqlite-vec and embedding support semantic episodic/event recall; failures fall back to keyword recall. |
| Unified `memory.retrieve()` | Open | `Pipeline.fetch_context()` loads layers separately and prompt building applies the global budget. |
| Provenance | Partial | Append-only provenance tracks write/revision/forget operations and has read-only query APIs, including a self-drift view. It does not yet make every aggregate point directly to an explicit list of event-log record IDs. |
| Explicit forgetting/supersession | Partial | Delete, forget-downgrade, revision/correction, closure matching, and audit trail exist. Generic automatic `superseded_by` conflict resolution does not. |
| Structured self model | Partial replacement | Retired `character_growth` must not be revived. Current trait state, author-note state, inner diary, and self-drift provenance cover parts of the goal, but are not one narrative self profile. |
| E. Query relevance in episodic score | Implemented | Keyword-IDF relevance and semantic similarity participate in fused recall scoring. |
| F. Strength decay floor | Implemented | Episodic recall uses a 0.3 decay floor. |

### Operations and safety

| Item | Status | Audit result | Follow-up |
|---|---|---|---|
| Backup/recovery/export | Partial, highest operational gap | Release updater backs up replaced program files; legacy migration can archive `data/`. Neither is a verified full private-state backup/restore/export workflow. | Implement snapshot manifest/hash, restore dry-run, recovery drill, retention, and secret-safe export rules for `data`, `userdata`, and local configuration. |
| Device identity and permissions | Partial | Scoped tokens, profiles, WS authentication, rotation, and revocation exist. There is no device pairing or per-device memory-read/delivery policy. |
| Task queue and scheduled work | Partial | Scheduler, maintenance triggers, defer queue, slow queue, and DLQ exist. Defer and slow queues are intentionally in-memory and lose pending work on restart. |
| Tool sandbox and permissioning | Partial | Whitelist, local policy, scopes, danger mode, confirmation, and write envelopes exist. This is not an OS/plugin sandbox. |
| Install and migration | Implemented with limits | Config template, auth setup, release updater, and v1 migration/recovery documentation exist. They do not replace user-data backup/recovery. |
| Server hub, admin, diagnostics | Implemented in backend scope | Pipeline/turn sink/registry, administrative routes, recall traces, provenance, vector, and hidden-state observability exist. Client UI completeness was not assessed. |

### Priority recommendation

1. Full private-state backup and restore drills.
2. Device pairing, per-device authorization, and delivery semantics.
3. Absence curve and structured time-tone layer.
4. Only then evaluate unified retrieve, adaptive trimming, or a distinct importance field.

## Batch: 5.15 desktop-state and mobile-delivery risks

| Item | Status | Audit result | Remaining risk / follow-up |
|---|---|---|---|
| StateEngine ref/observer delivery | Partial | `ChatWindow` still keeps one `StateEngine` in `useRef`, but this is safe: `StateEngine.applyPatch()` calls `emit()`, and rendering consumers subscribe with React `setState`. Polling already calls `applyBackendState()`. The `state-update` source type is reserved but no WS `state_update` frame is emitted or consumed. | Phase 3 must add the protocol frame and route it to `engine.applyBackendState('state-update', patch)`; add a focused subscription/render regression test. |
| Relaxed `tsconfig.json` | Recorded, acceptable debt | It sets `strict: false`, `noUnusedLocals: false`, and `noUnusedParameters: false`; `skipLibCheck: true` is also enabled. No `ignoreDeprecations` suppression was found. | Keep this as migration debt and tighten it deliberately, preferably file/domain by file/domain. |
| Google Fonts CDN | Open | `index.html` still preconnects to and loads Google Fonts. Local decorative fonts exist but do not replace the CDN families. | Bundle/license the required font files and declare local fallbacks before offline Tauri acceptance. |
| Mobile queue destructive poll loss | Implemented replacement | Backend poll is non-destructive. Flutter and Android persist seen IDs, then acknowledge the maximum sequence; acknowledgement failure does not advance the cursor. | This provides at-least-once delivery plus deduplication, not a general exactly-once transaction. |
| Multiple phones/tablets consume one queue | Open | The backend queue and acknowledgement cursor are per owner, not per device. One device can acknowledge messages before another reads them. | Requires device identity plus per-device cursor/ack state; decide whether delivery is broadcast, primary-device, or handoff. |
| Mobile token / public-network exposure | Partial | Mobile credentials are Android-Keystore-backed and should use the limited `mobile` scope; cleartext origin policy is constrained. | A public deployment still needs HTTPS, pairing/device revocation, and an explicit threat model. A token residing on an authenticated client is normal; an unscoped long-lived admin token is not. |

## Batch: v0.2 producer, probe, UI, and platform boundaries

### Producer and probe

| Item | Status | Audit result | Follow-up |
|---|---|---|---|
| Visual Perception Producer | Implemented for desktop; partial as a cross-device product decision | The desktop Tauri client owns capture. It requires both a local opt-in and a backend `sensor.write` preflight gate, samples every 60--3600 seconds (default five minutes), rejects a locked desktop, hashes frames in memory, uploads only meaningful changes, and records only a shadow trace. The backend never writes the image to disk or feeds the result into prompt/memory. No mobile screenshot producer was found. | Do a live desktop smoke test with both gates on/off and inspect the trace. Before adding mobile, choose a separate mobile permission, foreground/background rule, source identity, and retention contract; do not silently reuse desktop capture semantics. |
| Probe Capture Wiring | Implemented, but diagnostic-only | The active owner-chat path runs `admin/routers/chat.py::_probe_and_execute_tools()` in parallel with context retrieval when Path C is off. It captures the system prompt, short context, raw probe response, requested tool calls, and results in an in-memory five-turn per-user ring, readable through `/observe/probe`. QQ has the equivalent capture path. | This needs a real request smoke test if it is thought broken. It intentionally disappears after restart and is not a durable audit ledger. |
| "Weather did not use the probe" | Expected for proactive weather; conditional for chat | A user chat can select the `weather` info tool through Path A. When function-calling Path C is active, Path A is deliberately skipped and the main model owns tool selection. Scheduler weather alerts call the weather provider directly, not through a chat probe. | Debug by recording channel, active tool-loop state, probe snapshot, and tool trace for one concrete message; do not make the scheduler call the probe. |
| Standalone mode and model/tool routing | Implemented at the route level; runtime acceptance pending | Standalone mode only disables QQ and marks desktop active. It still uses the same owner-chat turn, per-character model routing, desktop settings model picker, and Tool Loop settings page. Path C therefore still replaces the pre-pipeline probe when enabled. | If the concern was a different "single-client/no-probe" mode, record its exact entry point and expected model. No separate mode-specific routing gap was found statically. |

### Tool-result envelope and EventBus

| Item | Status | Audit result | Follow-up |
|---|---|---|---|
| Minimal agent-loop `InteractionEnvelope` for `chat/tool_call/tool_result/probe_result` | Deferred by current architecture | Tool results already have explicit local ownership: Path A returns one bounded `tool_result` prompt layer for the current turn; Path C retains tool messages inside `run_agentic_loop()`; both avoid re-entering the stimulus gate or becoming memory by default. `PerceiveEvent` is only the low-trust reality stimulus gate. | Do not introduce a global envelope merely to label existing values. If cross-process replay or a second agent runner becomes necessary, first approve a versioned, redacted, owner-scoped event contract and define retention/idempotency. |
| EventBus next stage | Shelved | The authoritative interaction model marks `EventEnvelope`, kind routing, `kind=tool`, `kind=activity`, plugin system, and a unified dispatcher as historical/deferred. Existing channels are downstream fanout, not an EventBus. | Revisit only with a concrete producer/consumer that cannot be served by the current turn sink, scheduler, or tool loop. Keep `tool_result never re-enters as stimulus` as a non-negotiable boundary. |

### Desktop UI mod path

| Item | Status | Audit result | Follow-up |
|---|---|---|---|
| Split the chat UI | Partial replacement | `ChatWindow.tsx` is now primarily composition and controller wiring; sidebar, ribbon, chat panel, overlays, preferences, panes, dream, and appearance controls are separate components/hooks. It is still the application shell, so it is not yet a tiny pure layout file. | Continue only when a concrete new extension point demands it; avoid a cosmetic second split. |
| UI slots and class hooks | Implemented, deliberately narrower | `LayoutHost` exposes stable `ribbon`, `sidebar`, and `main` slots through `data-layout-slot`; `ChatPanel` separately constrains its registered main-region templates. The contract does not expose arbitrary topbar/right-panel/overlay component replacement. | Expand a slot only with an ownership, state, and safety contract; arbitrary React injection is function-mod/plugin work, not a CSS-layout feature. |
| Layout registry and manifests | Implemented | Built-in plus disk `layout.json` manifests are validated and loaded through the layout registry. Four bundled layout examples exist: `sidebar-right`, `mirror-stage`, `focus-stage`, and `presence-glass-atlas`; supported main templates are `stack`, `workbench`, and `hud`. | Keep the registry declarative. The current built-in fallback is only the default layout, so examples need packaging/release verification. |
| UI mod guide, examples, and tokens | Partial | `docs/layout-mods.md` and `docs/ui-mods.md` document layouts/themes and bundled examples. Theme tokens cover color, shape, fonts, Dream, and motion. Layout geometry is expressed through the manifest and registered regions, not broad CSS variables such as `--sidebar-width`. | This is a sound constraint for now. Add geometry tokens only after two real layouts need the same adjustable dimension. |
| Community/function mod market | Deferred | Themes and layouts execute no third-party code. The UI documentation explicitly defers function mods pending sandboxing and permission design. | Treat this as a plugin/security project, after device identity and tool sandbox work, not as a frontend marketplace ticket. |

### Character API and control-plane audit

| Item | Status | Audit result | Follow-up |
|---|---|---|---|
| Package a character plus chat/memory as an API | Partial foundation; not a public platform API | Character cards, active-character information, model-routing resolution, and asset bindings already have scoped endpoints. `/desktop/chat` is an owner-only application entry point over the live pipeline; its memory, locks, active character, and delivery behavior are not a stable embeddable API contract. | Call the future target a **Companion Runtime API**, not a character API. Start with a versioned owner/session identity, `POST /turn`, streamed turn events, explicit memory scope/retention, idempotency keys, capability discovery, and a privacy-safe export/import boundary. Do not expose the internal file schema or let a caller select arbitrary memory paths. |
| Admin/frontend/backend mismatch | Partial | There are substantial read-only panels: prompt/probe/tool traces, recall/vector/provenance, runtime, resource completeness, API contract checks, feature flags, and resolved character permissions. Desktop settings also surface model routing, per-character routing, thinking, tool loop, and visual local opt-in. They are distributed across two UIs and do not form one "configured -> resolved -> runtime observed" view. | P0 is an effective-control-plane endpoint and page that joins configured value, inheritance/override, enabled gate, owning process/client version, and last observed use. It should expose no secrets and make missing client capabilities explicit. |
| Sticker "does not send" | Implemented path; operationally unverified | Backend selection, emotion fallback, feature/probability control, per-character packs, cross-channel payload fanout, and desktop/mobile rendering exist. A 0.06 default trigger rate, disabled config, missing eligible asset folder, client receive toggle, or live transport can each produce no visible sticker. | Use resource-completeness, `/sticker-config`, one forced high-probability diagnostic turn, logs, and a live desktop/mobile receipt check before calling this a code defect. |

### Reasoning visibility and next-stage system risks

| Item | Status | Audit result | Follow-up |
|---|---|---|---|
| DeepSeek probe visibility and "speaking/tool order" | Partial | Probe snapshots and tool traces can show the selected calls and their bounded results. Desktop also receives a transient `tool_status` indicator during a Path C loop. This is adequate for an operator trace, not a model-thought display. | Add a redacted lifecycle timeline (`probe decided`, `tool started`, `tool finished`, `reply started`, `reply sent`) with correlation IDs if needed. Never make hidden reasoning a product/debug payload. |
| Chain-of-thought visualization | Not a valid target | Native `reasoning_content` and inline think tags are deliberately discarded; generated monologue is injected for one turn only and is never broadcast, stored, or added to history. | Keep this boundary. Offer a short, authored explanation or a safe decision/tool trace instead of raw chain of thought. |
| State explosion / single source of truth | Partial | Several domains already declare owners (backend runtime, channel/turn sink, desktop `StateEngine`, memory, Dream/Stage), but there is no cross-domain effective-state inventory. | The effective-control-plane audit above is the smallest useful next step; do not centralize unrelated state into one JSON document. |
| Schema versions and migrations | Partial | Data-path migration and compatibility fallbacks exist, but there is no universal schema registry, migration ledger, and restore drill for all private state. | Couple any broad schema change to the backup/restore priority item. |
| Permission and trust | Partial | Scoped tokens, local tool policy, confirmation, danger mode, and source gates exist. Device pairing, per-device data scopes, third-party plugin sandboxing, and a public threat model do not. | Prioritize before public API, Watch, or function mods. |
| Observability and extensibility | Partial | The system has numerous focused traces and deliberately declarative theme/layout extensions, but no unified configuration audit and no general plugin lifecycle/contract suite. | Preserve the current narrow contracts; add compatibility and capability tests before expanding extension power. |

## Evidence boundary

- This is a read-only source audit across the backend, desktop client, and mobile client.
- No tests, device runs, release builds, or live recovery drills were run for these audit batches.
- Existing unrelated worktree changes were preserved.

## Batch: final legacy notes — recall quality, expression, and content assets

### Live recall and proactive expression

| Item | Status | Audit result | Follow-up |
|---|---|---|---|
| `spontaneous_recall` feels random | Partial | The active proposer selects only the strongest recent candidate window, excludes memories recently recalled, and marks the chosen memory/topic after a successful send. It still sorts primarily by strength and timestamp, then leaves final selection to a random choice; it has no explicit current-topic or relationship-continuity score. The older direct scheduler routine has the same issue, although it is normally disabled in live proposer mode. | Add a traceable candidate score and reject contextually orphaned memories before changing prompts. A short history of the actual delivered recall and its topic is needed for acceptance. |
| Short intervals and disconnected proactive messages | Partial, operationally unverified | The shared proactive ledger enforces a default 90-minute global gap, per-trigger cooldowns, daily caps, jitter, and a one-item continuity hint. This should prevent normal proposers from clustering, but emergency paths and legacy/direct sends are exceptions. The continuity hint records the seed/prompt gist rather than a semantic summary of the delivered reply. | First inspect the ledger and trigger trace from an affected period. Then close any direct-send bypass and record a compact reply/topic continuation record; do not just increase cooldowns blindly. |
| Proactive messages missing on mobile | Implemented and user-confirmed | Scheduler sends go through the assistant-turn sink with `fanout="all"`; the mobile queue supports non-destructive polling, persistent sequence acknowledgement, and client deduplication. The user has now confirmed active-message delivery to mobile. | Remove this from the active incident list. Future work is trigger quality, not mobile fanout. |
| Third-person trigger narration | Partial | Many scheduler seed prompts still describe the user as “她”; the recall seed explicitly says “你…说给她听”. Short-term history has a third-person cleanup heuristic, but it only acts after generation and is intentionally conservative. | Replace user-facing trigger seeds with a single second-person contract where safe, then add output-contract cases for short replies. Do not apply a blind global text replacement: third-person may refer to an NPC or quoted content. |
| Repeated openings such as “现在，…” | Partial | Prompt layers already retain recent openings, inject a no-repeat hint, and persist anti-collapse / stream-collapse correction signals. Those checks are prefix-oriented, so semantic paraphrases or a model-specific habitual opener can pass. | Do not add random seed noise. Add a measured recent-opening n-gram/similarity check with an explicit one-turn corrective constraint (or low-cost retry only on violation); compare it in a fixed eval corpus first. |

### Memory, narration, and group context

| Item | Status | Audit result | Follow-up |
|---|---|---|---|
| Temporary versus long-term profile facts | Partial, with a safe read-side improvement already present | Prompt layer 5 now whitelists only compact objective core fields. Tagged preferences/habits/health are relevance-or-recency selected; `status.project` expires after 30 days. Legacy `stable`/`misc` facts and scalar `interests` stay on disk but are no longer ambient prompt context. The reported “long historical overview” can therefore also originate from identity, episodic, mid-term, pinned facts, or author notes. | Export one prompt-layer snapshot and classify sources before migrating data. Use a preview-only migration: project/status and short-lived tastes; habit/health medium-term; enduring values/relational stance in identity; episodic events in episodic memory. Preserve provenance and never let an automatic classifier delete facts. |
| Vector total `0`, dimension `1024` | Blocked / ambiguous observability defect | `vector_store.stats()` deliberately returns the same `{total: 0}` for an empty store, unavailable database/native extension, schema error, failed embedding configuration, provider failure, or dimension mismatch. `self_hosted` embedding is explicitly unimplemented; only configured OpenAI-compatible embedding can write vectors. | Make a read-only vector health result first: DB/native availability, configured-provider validation without secrets, last embedding attempt/error, dimensions, and per-source count. Then run a controlled rebuild/recall case. Do not treat the displayed zero as proof of one cause. |
| Dream narration pronouns | Implemented contract; runtime violation requires a bug example | Dream prompts already lock the character to “我”, the user to “你”, forbid narrating the user, and prohibit using “她” for the user. | Do not render-rewrite “她→你” or “我→他”: it corrupts NPC references and speaker meaning. Capture an offending reply and repair the generator/output validator at the segment boundary. |
| Group-chat history timestamps and sorting | Implemented for normal group context | Group-context rendering ranks older context for relevance, then merges and emits the selected transcript in timestamp order with `[timestamp] sender: content` annotations. | If the observed issue is a Stage or Dream-stage transcript, audit that separate path with a concrete payload; do not duplicate the normal group formatter. |
| Two-hop episodic recall | Implemented, default off | A `two_hop_enabled` feature flag expands through shared topic keywords, has a two-item hard cap, link-frequency cap, score threshold, and trace provenance. | Enable only after vector health and recall evals are green; inspect topic drift before making it default. |
| Tag conflict / insertion order | Implemented for worldbooks; partial for episodic recall | `lore_engine` and dream-world entries match keywords then sort by `insertion_order`. Episodic memory intentionally ranks by recall score rather than a manual insertion priority. | Keep the two semantics separate. Add episodic manual pin/priority only if a real curation workflow needs it. |

### UI, output, growth, and packaging ideas

| Item | Status | Audit result | Follow-up |
|---|---|---|---|
| Repository renaming leftovers | Deferred documentation cleanup | User-confirmed current remote backend repository name is `PresenceKit`, with v0.2.3 released. Do not rewrite remote/clone URLs to `His-presence` unless a separate remote rename actually occurs. Local-development/product references remain a content-aware decision. Historical sample memory mentioning an older project name is not a repository reference. `buttplug` `ClientName` is a handshake identifier, not documentation. | Do a content-aware docs-only pass, not global replacement. Keep historic test memory; change the device handshake only with a compatibility smoke test and explicit approval. |
| Personality-dynamics sliders | Deferred | No stable component/state contract was found. | Define which observable state they control and guard against sliders becoming an untraceable second prompt source. |
| Rich text / emotional typography | Partial replacement | This desktop client is React/Tauri, not Qt. It safely parses only `<hl>`, `<big>`, and `<sm>` inline tags; narrative segments already have a structured parser. | Extend the existing safe renderer for approved action/strike/link semantics if a concrete visual design needs them. Never enable arbitrary HTML/CSS from model output. Hover/click behaviors need an explicit interaction and accessibility contract. |
| Dynamic/characterful streaming | Partial | The desktop path streams with paragraph-safe buffering; Dream has pseudo-stream typewriter replay. There is no mood-to-speed/chunk policy or action-first scheduler. | Add a display-layer pacing controller after output-quality fixes, using complete safe segments rather than raw token chunks. Treat yandere overlays/mouse reactions as a separately consented desktop visual feature. |
| Autonomous knowledge growth | Partial | X3 web search can persist externally sourced material into vector storage with source isolation, and a feature flag can prompt tool use. No unattended generic web-crawl-to-`yexuan_notes` job was found. | Keep background research opt-in, rate-limited, attributed, reviewable, and isolated from personal memory. “Self-awareness” and changing model weights are not runtime product features. |
| Mood-driven temperature | Foundation only | Model presets pass normal provider parameters including `temperature`; no mood/scenario resolver controls it. | If added, make a deterministic scene/relationship mapping chosen by the system, logged per request, bounded by preset/provider limits, and evaluated for regressions. |
| DS draft plus Claude polish | Deferred | Multi-preset routing exists, but there is no draft/critic/rewrite pipeline. | Do not add it ahead of output evaluation: it costs an extra model round trip and can erase voice or memory grounding. Prototype only with a fixed rubric and side-by-side examples. |
| Worldbooks and export | Partial | Keyword lorebooks support `insertion_order`; reality and dream have separate management paths and JSON-oriented import/export. A unified global/per-character worldbook taxonomy and Tavern-compatible interchange are not a single active product contract. | First decide scope inheritance and collision rules; then add import/export adapters without exposing private memory. |
| Static asset classification | Implemented foundation | Authored private assets are routed through `userdata`/asset registry; release-owned examples belong under `bundled`. | Keep assets distinct from memory and plugins; extend the registry only when a new asset category has lifecycle/permission requirements. |
| Dynamic Author's Note placement | Deferred | Notes are rotated and injected as a fixed late layer 11, alongside consistency and style corrections. | Placement changes alter attention and safety behavior; test them as prompt variants before making them configurable. |
| “Diary detection” | Open / underspecified | Diary read/reminder flows exist, but no defined contract was found for detecting that a user is currently writing a diary. | Specify the source first: pasted text, an opt-in local file/editor watcher, or a client activity signal. Each has different consent and privacy requirements. |

## Portfolio priority after the full backlog audit

If the goal is **product trust and immersion**, execute in this order:

1. **Make live failures observable, then repair them:** vector health/rebuild and a one-session proactive delivery trace (trigger, ledger decision, fanout, mobile receipt, reply/topic). This turns the current “0 vectors / strange spontaneous messages” reports into falsifiable bugs rather than prompt guesses.
2. **Protect irreversible private state:** full backup, restore dry-run, recovery drill, and manifest coverage for private data/configuration. Do this before any memory migration or broad multi-device work.
3. **Restore conversational continuity:** score/filter spontaneous recall by relevance and recent conversation, enforce second-person trigger/output contracts, and strengthen opening-diversity evaluation. Include mobile proactive E2E in its acceptance test.
4. **Cleanly classify existing memory:** use a prompt-layer snapshot and preview-only, provenance-preserving migration of old profile facts. Do not begin two-hop recall or more aggressive semantic retrieval until vector health is known.
5. **Make the control plane legible:** one effective-config/runtime-observation view, then device pairing/per-device cursors before Watch, public runtime APIs, or function mods.

Everything else in this batch—dynamic temperature, dual-model polishing, broad rich-text effects, personality sliders, UI marketplace, autonomous research, and dynamic Author's Note placement—is valuable only after these foundations have evidence and regression coverage.

## Corrections confirmed after audit

- Mobile receives proactive messages correctly; the current temporary containment is a substantially higher global cooldown while individual triggers await redesign.
- The local toy MCP integration is connected. It is no longer an integration blocker; its permission and recovery boundaries remain relevant.
- The current remote backend repository is `PresenceKit`; v0.2.3 has been released. This is user-confirmed release state, not independently network-verified in this audit.

## Backup and recovery implementation shape

The existing updater backup is a **program rollback** snapshot. It preserves private roots during an update, but it is not a private-state backup and must not be presented as one.

### First delivery: conservative and recoverable

1. Add an offline/maintenance-only `backup-state create` command. It must refuse while the service is running (first version), rather than attempting a live copy while queues and memory files are changing.
2. Snapshot exactly the protected private state: `data/`, `userdata/`, `config.yaml`, optional `config.local.yaml`, and optional `secrets.local.yaml`. Exclude source code, `bundled/`, environments, caches that are truly regenerable only after they are explicitly classified, and updater program backups. Keep the backup destination outside the installation directory.
3. Build the archive in a temporary sibling directory, enumerate every included file, calculate SHA-256 and byte count, then write a versioned manifest containing product version, layout marker/schema, creation time, included roots, and hashes. Never put token plaintext in the manifest or command output.
4. Encrypt portable/off-machine archives. A local-only archive may rely on an explicitly chosen protected volume, but the command must report that protection choice rather than imply encryption. Retain a small rolling policy (for example, seven daily and four weekly snapshots) without deleting the newest verified snapshot.
5. Add `backup-state verify` (hashes, archive readability, manifest/schema) and `backup-state restore --target <empty-directory>`. Restore must refuse a non-empty target by default and never overwrite the live installation.
6. Recovery drill: stop the service; create a snapshot; restore it into a fresh directory; verify hashes and data layout; run authored-root dry-run; start only in standalone/no-outbound mode; prove configuration/auth/character/pipeline initialization; then compare a selected memory, authored asset, and dream/state record against the manifest. Only after that may a human explicitly switch the live installation.

### Acceptance and migration rules

- A completed archive is not “backed up” until `verify` passes and at least one restore drill succeeds.
- Migration or profile reclassification must first create and verify a snapshot; restoration is directory-based, not an in-place downgrade.
- Record failures as structured, secret-free results: missing root, unreadable file, hash mismatch, unsupported layout, restore target non-empty, or startup validation failure.
- Add focused tests for file selection, manifest tamper detection, missing optional configs, refusal of live/non-empty targets, and restore round-trip. The final acceptance still needs one real local recovery drill.
