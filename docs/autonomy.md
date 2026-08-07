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
  "source": "sensor|scheduler|desktop_wake|interval|schedule|overflow",
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
stable routine key or by `reason` and memory key. The scheduler `_check_*`
module is the only producer for configured morning/night/midday/random routine
facts; the runner does not synthesize a second clock-based copy. Routine facts
default to `action_mode=none` and never force `TALK`. Expired candidates are discarded before queueing;
urgency can elevate the recorded priority but never bypasses dream, active-user,
conversation, or budget gates.

### Desktop reopen signal

`POST /desktop/wake` Path B is a signal producer, not an assistant-turn
executor. After the existing perceive-event dedupe and Dream Guard accept the
request, `enqueue_desktop_wake_signal()` stores one `desktop_wake` signal with
`action_mode=reflect` and a ten-minute TTL. Evidence contains only the reopen
fact, a bounded offline duration (maximum 30 days), a safe perceive event id,
and a truncated SHA-256 fingerprint of the perceive dedupe key. Raw `last_seen`, raw
`last_seen_at`, request bodies and the dedupe key are not persisted in the
signal.

The HTTP response acknowledges queueing and does not promise speech. The signal
can merge with other candidates in the next tick, and the runner may finish
silent, use tools only, or call `talk_owner` once. Perceive duplicates and Dream
blocks never enqueue. If autonomy is already disabled, no wake signal is
stored; if it is disabled after queueing, the pending wake is removed and
recorded as a terminal suppression. Expired wake signals also receive terminal
job/run records, and a Dream block after job creation is terminal rather than
retryable. These one-shot rules prevent a stale reopen from firing after a
later re-enable.

Dream blocking is applied per signal when an opportunity contains a desktop
reopen plus other sources. The blocked parent job always finishes. Its
`desktop_wake` signal receives a terminal `not_replayed` event, while each
still-valid non-wake signal is merged into one bounded child retry job. The
child keeps the shortest remaining signal TTL (and never extends the parent
TTL), records `retry_parent_job_id` / `retry_parent_run_id`, and retains the
normal Dream retry backoff. Non-wake signals that expire before the split get
terminal `expired` events instead. A pure non-wake opportunity continues to
retry the original job; a pure wake opportunity creates no child.

Memory reactivation reuses the scheduler recall ledger with separate stages.
Selecting a candidate records its stable memory key in opportunity evidence; a
completed system recall is reported as `memory_read`; the first completed model
evaluation records `memory_candidate_evaluated`; only a delivered `talk_owner`
call writes the existing successful-recall ledger and reports
`memory_recall_talk_sent`. Silent, blocked, failed, and canceled delivery never
pretend to be a successful recollection. A recently evaluated/recalled memory is
suppressed for the recall window unless a caller supplies explicit new anchored
context, such as a new owner turn or new evidence.

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

## Unified Effective State

`GET /admin/autonomy/effective-state`（`state.read`）是 scheduler/autonomy 控制面的只读
生效状态契约。它是管理页读取开关的唯一后端入口，返回 `contract_version`、配置值、
effective runtime value、override source、`restart_required` 和唯一 runtime consumer。
契约还包含 scheduler task availability、autonomy queue/circuit、`talk_owner` gate、
全局发送冷却、autonomy evaluation/daily talk budget，以及每个 trigger 的
`migrated` / `maintenance-only` / `retired` / `active` 生命周期状态。

顶层 `proactive.state` 只使用 `enabled`、`disabled`、`unavailable`、`queued`、`running`、
`cooled_down`、`blocked`。`proactive.reason` 是当前最先命中的阻断原因，因此客户端不
需要拼接多个 status/config/ledger 端点来猜测“为什么没有主动行为”。所有这些配置均为
hot-reload 或 durable autonomy state，`restart_required` 当前为 `false`。

`POST /scheduler/trigger/{name}` 与 `POST /admin/autonomy/test-enqueue` 是 test-only 入口。
它们只排队事实/测试任务，响应明确标记 `direct_delivery=false`，生产发送仍必须经过
scheduler tick、autonomy admission 与 `talk_owner`。

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
| `expired` | The signal or opportunity reached its TTL without evaluation. |
| `blocked_or_failed` | A gate, budget, lease, model, or tool failure stopped evaluation. |

Prompt snapshots remain behind the existing admin-only run prompt endpoint and
are not included in this state-read surface.

Split Dream retries are correlated on this surface by the child opportunity's
`retry_parent_job_id` / `retry_parent_run_id` and the parent run's bounded
signal terminal/child-queued events. No separate wake or retry ledger exists.

For `desktop_wake`, the safe signal id is the HTTP `correlation_id`; the signal
also carries the perceive event id and a dedupe fingerprint. The existing
perceive-event audit records accepted, duplicate and Dream-blocked gate results,
while autonomy opportunity/run records show merge membership and the terminal
disposition. No separate wake ledger is introduced for Path B.

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
