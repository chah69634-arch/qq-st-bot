# Runtime Lifecycle

> Emerald-Presence runtime startup order and long-lived component ownership.
>
> This document describes the current runtime topology.
> It is not a future architecture proposal.

---

## 1. Process Entry

Backend entry point:


python main.py


`main.py` owns application startup.

No subsystem should independently create global runtime instances or background services outside the startup path.

---

# 2. Backend Startup Sequence

Current startup order:


main.py
|
+-- load configuration
|
+-- validate admin authentication
|
+-- load active character
|
+-- initialize lore engine
|
+-- create Pipeline
|
+-- register Pipeline
|
+-- register slow handlers
|
+-- cleanup pending state
|
+-- start background services
|
+-- start HTTP/admin service


---

## 3. Core Runtime Owners

### Pipeline

Owner:


main.py


Creation:


Pipeline(character, lore_engine, active_character_id)


Registration:


pipeline_registry.register()


Lifetime:


process lifetime


Responsibilities:

- conversation processing
- prompt construction
- memory interaction
- LLM execution coordination

Other modules should access Pipeline through the registry instead of creating their own instance.

---

## 4. Scheduler Lifecycle

Owner:


main.py


Startup:


scheduler.start()


Lifetime:


background asyncio task


Responsibilities:

- periodic checks
- proactive proposals
- trigger evaluation
- gating
- execution coordination


Scheduler structure:


scheduler loop
|
+-- trigger modules
|
+-- proposer registry
|
+-- gating
|
+-- execution
|
+-- turn sink / output


Important:

Scheduler depends on Pipeline being initialized first.

Trigger execution before Pipeline registration is invalid.

---

# 5. Registry Ownership

The system currently uses several registries.

They solve different problems and should not be merged without a clear reason.

---

## Pipeline Registry

Purpose:

Store the active Pipeline instance.

Flow:


main.py
|
v
Pipeline creation
|
v
pipeline_registry.register()


---

## Tool Registry

Purpose:

Register available tools.

Flow:


tool module
|
v
tool dispatcher registry
|
v
LLM/tool execution


---

## Scheduler Proposer Registry

Purpose:

Allow trigger modules to submit proposals.

Flow:


trigger module
|
v
register_proposer()
|
v
scheduler gating
|
v
execution


---

# 6. Long-lived Components

| Component | Owner | Lifetime |
|---|---|---|
| Pipeline | main.py | process lifetime |
| Lore Engine | main.py | process lifetime |
| Scheduler Task | scheduler.start() | process lifetime |
| Hardware job manager | main.py → `core.hardware.jobs.startup()` | process lifetime; workers stop/cancel during shutdown |
| FastAPI Admin Server | main.py | process lifetime |
| Sensor workers | corresponding runner | process lifetime when enabled |

The FastAPI admin server and QQ listener run behind separate service boundaries in
`main.py`. A bind failure, `SystemExit`, or ordinary exception in one service is
logged without cancelling the other service. Cooperative task cancellation still
propagates during process shutdown.

---

# 7. Background Workers

Background services must have:

- explicit owner
- startup location
- shutdown behavior

Current examples:


scheduler task
sensor runner
visual observation runner
hardware workers

The hardware job manager is started by `main.py` after Pipeline setup. It marks
jobs left active by a previous process as `expired`, attempts an explicit stop,
and unregisters its device-disconnect listener during shutdown. A worker never
starts from module import.


A module should not silently create a background task during import.

---

# 8. Import Rules

Importing a module should not:

- start threads
- create network connections
- create global runtime objects
- launch asyncio tasks

Initialization belongs to startup code.

---

# 9. Event Flow

Current message flow:


Input
|
v
Channel / API
|
v
Pipeline
|
v
LLM + tools + memory
|
v
Turn Sink
|
v
Output


Proactive flow:


Sensor / Scheduler / Trigger
|
v
Proposal
|
v
Gating
|
v
Execution
|
v
Pipeline / Output


---

# 10. EventBus Status

Current system does not use a universal EventBus.

Existing mechanisms:

- pipeline registry
- tool registry
- proposer registry
- perceive_event
- turn sink

These currently represent different boundaries.

A future EventBus should only be introduced when there is a clear requirement for:

- cross-module asynchronous notification
- multiple independent consumers
- lifecycle ownership

Do not replace existing registries with a generic event bus only for abstraction.

---

# 11. Dream continuation recovery (Brief 170)

After channels are registered during `main.main()`, the process schedules the
bounded `core.dream.reality_continuation.recover_pending()` scan. It consumes
only the existing Dream exit lifecycle ledger and requeues `pending`
or `failed` rows. The continuation worker then waits the per-owner
conversation gate and uses the normal Reality pipeline; it is not a scheduler
tick, proposal, winner, or separate persistent ledger. The send marker is
written after `record_assistant_turn()` returns, while the client handles the
matching Dream active-to-closed transition and one-shot navigation close.

# Brief 171: Remote deployment preflight

`deployment.mode` is process configuration (`local` by default or
`remote_server`) and cannot be changed by a request, prompt, or model. The
read-only `/system/deployment-preflight` projection reports bind mode,
declared TLS/WSS, persistent-root writability, desktop WS state, disabled
capabilities, diary-sync state, and that no port scan was performed. It is a
readiness projection, not proof that an external tunnel or backup is healthy.

In remote mode server-local OS operations and client file fallbacks are
disabled. Desktop actions use the existing heartbeat/ack WebSocket path;
owner turns and mobile polling remain normal HTTP/queue paths.

# 12. Known Gaps

## Missing shutdown contract

Current lifecycle documentation focuses on startup.

Future work:

- service shutdown order
- task cancellation
- resource cleanup


## Missing runtime topology view

Future improvement:

Document:

- running workers
- owned tasks
- persistent state owners
- communication paths


## Brief 176：Dream WAKE 确认与跨进程收口

Dream 的 `DREAM_EXIT_REQUESTED` 是退出确认待决态，不是已关闭态。客户端的“留下”通过带同一 `dream_id` 的 `/dream/resume` 恢复 `DREAM_ACTIVE`；“还是要醒来”、再次 WAKE 或 Esc 通过唯一的 `force_exit_dream()` / `_do_close_dream()` 收口。只有后端确认 close/archive 成功后，桌面窗口才关闭；请求失败时保留 current session 和可重试出口。

后端关闭成功的持久不变量是：active `dream_id` 清除、`last_dream_id` 固定、current transcript 移入对应 archive，后续 archive replay 只读且不能 resume、send、WS/TTS 或重新写 current。`archive_ok=false` 时保持 `DREAM_CLOSING`，不得由 UI 关闭掩盖失败。重复调用返回首次关闭 metadata，并通过 operations 观测重复次数；旧 `dream_id` 的迟到请求不得影响新梦。

这条链路的单元/协议检查不替代真实跨进程验收。完整验收仍需在不污染真实 runtime/userdata 的隔离环境中，真实启动 backend 与 desktop，验证“挽留 → 确认醒来 → 窗口关闭 → 只读回放 → 旧梦不可发送 → 新梦 ID 不同”。
