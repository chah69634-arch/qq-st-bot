# Signal-first Autonomy

This document defines the v1 boundary for proactive work. A scheduler or sensor
may report facts, but it does not generate a user-visible line. `core.autonomy`
is the only proactive decision and delivery path; `talk_owner` is its only
user-facing outlet.

## Versioned Contract

Signals use `autonomy-signal.v1`:

```json
{
  "version": "autonomy-signal.v1",
  "source": "sensor|scheduler|interval|schedule|overflow",
  "evidence": [{"fact": "..."}],
  "reason": "A bounded explanation for considering this opportunity.",
  "expiry": 0,
  "priority": 0.0,
  "memory_query": null,
  "action_mode": "none|reflect|use_tools|talk",
  "signal_id": "stable-per-signal-id",
  "expires_at": 0,
  "urgency": 0.0,
  "confidence": 0.0,
  "suggested_action": "silent|message|question|suggestion|tool_then_talk",
  "created_at": 0,
  "id": "stable-per-signal-id"
}
```

`evidence` is system-provided fact data, not a user statement. `expiry` is a
Unix timestamp; zero means no explicit expiry. `memory_query` is an optional
anchored query and is never inferred from a greeting or time-of-day label.

Signals produced during one scheduler tick are merged into one
`autonomy-opportunity.v1` before a job is queued:

```json
{
  "version": "autonomy-opportunity.v1",
  "signals": [],
  "priority": 0.0,
  "reason": "Combined bounded reasons.",
  "expiry": 0,
  "memory_query": [],
  "action_mode": "none|reflect|use_tools|talk",
  "created_at": 0,
  "id": "opportunity-id"
}
```

The opportunity is persisted on the durable autonomy job. The runner receives
the complete opportunity, performs bounded memory recall (`allow_strengthen =
false`), and receives an explicit local reality timestamp. Ordinary model text
is private. It may use the autonomy allowlist, call `talk_owner` once, or end
with no user-visible message.

The runner keeps this prompt projection intentionally smaller than a normal chat
prompt. It includes system-observed activity, bounded profile/mid-term/history
layers, and a system-executed `memory_query` layer. Recall cards retain their
source, event/recorded timestamps, speaker provenance, strength, and source-turn
IDs. Missing or unknown provenance is not a valid historical anchor, and signal
evidence is always labeled as a candidate reason rather than past dialogue.
Successful tool results and active hardware jobs are separate factual layers;
neither one requires a user-facing message. `talk_owner` rejects unsupported
memory claims such as an ungrounded 'I remember'/'you said' statement.

Scheduler and sensor adapters live in `core.autonomy.signal_adapters`. They
only emit bounded facts for routine/time-background, heart-rate state changes,
memory reactivation, unfinished topics, desktop reopen, and runtime restart.
Candidates in the same 15-minute opportunity window are deduplicated by
`reason` and memory key. Expired candidates are discarded before queueing;
urgency can elevate the recorded priority but never bypasses dream, active-user,
conversation, or budget gates.

When autonomy is enabled, the scheduler's native proposal pass remains a
read-only shadow audit. It does not execute a second proactive turn; the
autonomy runner is the sole evaluator and delivery path for that tick.

## Retired Direct Executors

Scheduler-facing conversational triggers are compatibility producers only.
If an old callback reaches `scheduler._pipeline_send`, the callback's prompt is
discarded and a bounded signal is persisted for the next autonomy tick. It does
not enter the LLM pipeline or a channel. The runner drains all pending signals
once, merges them into one opportunity, and `talk_owner` remains the only
user-visible outlet.

The migration currently covers routine greetings, night/midday cues, fixed
random messages, ordinary heart-rate/sensor attention, recall/follow-up,
calendar reminders, and birthday candidates. Birthday and serious health
candidates retain higher signal urgency, but do not bypass autonomy admission,
the talk gate, conversation serialization, active-user cancellation, or the
proactive ledger.

Manual scheduler triggering queues the same kind of opportunity. It never
forces a direct assistant message. Delivery also records an opportunity
correlation id; an already claimed id is rejected before another `talk_owner`
send can happen.

## Observable Outcomes

`GET /observability/autonomy-opportunities` (scope `state.read`) returns a
redacted lifecycle stream. The `status` field distinguishes:

| Status | Meaning |
|---|---|
| `unevaluated` | Signal/opportunity is queued or currently leased. |
| `evaluated_silent` | The opportunity was evaluated and no message was chosen. |
| `tools_completed_no_talk` | Tools completed, but `talk_owner` was not called. |
| `talk_sent` | `talk_owner` delivered through `turn_sink`. |
| `canceled_user_activity` | A real user turn took priority and canceled the run. |
| `blocked_or_failed` | A gate, budget, lease, model, or tool failure stopped evaluation. |

Prompt snapshots remain behind the existing admin-only run prompt endpoint and
are not included in this state-read surface.

## Migration Registry

`core/scheduler/gating.py::MIGRATED_TRIGGERS` is the retired-speech registry.
Names in this set may still appear in cooldown, proposer, or audit code, but
their executor is never run by the gating layer and the compatibility
`_pipeline_send` boundary can only persist a signal. This covers time-based
greetings/reminders and recall, watch and sensor events, diary and period
reminders, overflow, presence nag, dream exit, festival/timenode, garden
events, coplay commentary, and letter writer.

Maintenance-only tasks are deliberately outside this registry. Examples are
`diary_inject`, episodic/log cleanup, memory janitor, event-log salvage,
hidden-state decay/consolidation, storyline aggregation, and garden state
maintenance. They continue to mutate their owned state without creating an
assistant turn or entering `talk_owner`.

No global EventBus or model-visible trigger tool is introduced by this design.
