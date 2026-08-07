# 149 收口 desktop_wake Path B 到 Signal-first Autonomy

## 背景

Brief 144/145/147 已将 `desktop_wake` 列为应迁移的主动信号来源，但当前
`admin/routers/chat.py::desktop_wake()` 的 Path B 仍在 HTTP 请求内直接执行
`fetch_context -> build_prompt -> run_llm -> record_assistant_turn`。它虽已有
`perceive_event`、Dream Guard、`conversation_lock` 与 proactive ledger，却绕过了
autonomy 的 opportunity 合并、静默决策、用户活跃取消、未回复上限、日预算、run 记录及唯一
`talk_owner` 出口。

`core.autonomy.signal_adapters.adapt_desktop_wake()` 已存在，说明数据契约已具备；本工单
只完成该来源的实际接线和旧直发分支退役。

## 目标

将 Path B 从“桌宠重开时同步强制生成一句话”改为“产生一个有时效的 reopen 信号，交由既有
autonomy runner 决定静默、工具活动或发言”。用户可见主动消息只能由现有 `talk_owner` 发送。

Path A 的历史主动消息回放不是本工单的迁移对象，必须维持现有语义：它只读取 `last_seen`
之后尚未回放的持久 assistant trigger turn，并通过 wake delivery ledger 保证至多返回一次。

## 实施范围

### A. Path B 改为信号生产者

1. 保留 `PerceiveEvent(source="desktop_wake", kind="wake", payload={})` 作为 HTTP 入站的
   去重和 Dream Guard 边界。`last_seen` 绝不可进入该 payload 或 dedupe key。
2. `PerceiveStatus.ACCEPTED` 后，解析与事件相同的活跃角色作用域，并通过
   `core.autonomy.signal_adapters` 加一个明确的 enqueue helper，复用
   `adapt_desktop_wake(last_seen=...)` 生成事实型 `ProactiveSignal`。
3. signal 必须带稳定的来源/关联信息：`source="desktop_wake"`、reopen 事实、经边界校验的
   离线时长、TTL、`event_id`/`dedupe_key` 的安全关联值。不要把旧的自然语言 seed prompt
   或未经约束的 HTTP body 原样写入 signal。
4. signal 通过已有 `core.autonomy.store.enqueue_signal()` 落盘，由既有 scheduler tick 消费；
   HTTP handler 不得创建 task、直接执行 runner、调用 LLM、调用 `record_assistant_turn` 或写
   proactive ledger。
5. `desktop_wake` 属于一次性重开事实。autonomy 全局关闭时，返回明确的非发送结果且不保留
   可在日后突然补发的 wake signal；梦境阻断、重复、过期同样不得留下可重放的候选。

### B. HTTP 与桌宠协议

1. Path A 保持现有返回：`source="pending_trigger"`、`reply`、相等的 `turn_id/msg_id`，以及
   delivery ledger 的一次性语义不变。
2. Path B 的 accepted 响应改为无文本确认，例如
   `{ "reply": null, "source": "queued_autonomy_signal" }`；可额外返回不含敏感内容的
   correlation/expiry 诊断字段，但不能伪造 `turn_id/msg_id`。
3. 后续只有 autonomy 实际决定 Talk 时，桌宠才经现有 `channel_message` / `message_segments`
   收到正常主动消息；autonomy 选择 silent、tools-only、预算耗尽、用户活跃、未回复上限或 DND
   都是合法结果，HTTP 不应把它们伪装成失败或承诺“马上回复”。
4. 更新 `docs/desktop-client-protocol.md`、`docs/channels.md` 中 `/desktop/wake` 的 contract。
   发布给桌宠客户端的协议变更必须注明：Path B 不再同步返回 LLM 文本，客户端应处理 queued
   响应并继续监听已有 WebSocket 消息。桌宠仓若需适配，另开跨仓工单，不把该改动偷偷塞进后端。

### C. 观测与兼容清理

1. 既有 autonomy opportunity/run 观测必须能看到 `desktop_wake` 的 signal、合并结果、最终
   disposition 与 correlation；无论 silent、过期、重复或 Talk，都可解释。
2. 保留 `perceive_event` 审计记录，关联其 accepted/duplicate/dream-blocked 结果；不要另造
   无观测的 JSON 台账。
3. 删除 Path B 内已退役的 prompt capture、reality scrub、turn sink、ledger 直写代码，以及
   只守卫这些实现细节的测试。新守卫测试应验证行为契约，而不是要求 handler 文本中仍出现
   `record_assistant_turn`。
4. 更新 `docs/scheduler.md` 与 `docs/interaction-event-model.md`：`desktop_wake` 从 trigger
   直发路径移至 signal-first autonomy；不要把它重新接到 `_pipeline_send()`，后者是迁移兼容面，
   不是新的主动消息出口。

## 验收测试

使用 `pytest -n auto` 跑相关测试，至少覆盖：

1. Path A 有未回放 trigger turn 时，仍同步返回同一条消息与 canonical ID，且并发/重试至多回放一次。
2. Path B accepted 时只入队一个 `desktop_wake` signal；HTTP handler 全程不调用 LLM、
   `record_assistant_turn`、`talk_owner` 或 direct channel send。
3. 同一 dedupe bucket 内、不同 `last_seen` 的重复请求只有一个 `PerceiveEvent` accepted 和一个
   pending signal；`last_seen` 不污染 perceive dedupe key。
4. Dream Guard 阻断、perceive duplicate、autonomy 关闭和 signal 过期时均不产生 assistant turn，
   也不留下未来可补发的 wake 机会。
5. runner 消费 wake signal 后，分别覆盖：silent、tools-only、Talk sent、用户活跃取消、DND、
   日预算/未回复上限。只有 Talk sent 走 `talk_owner`，且最多一次。
6. wake signal 可与同一窗口的其他低权重信号合并，而不会导致两条主动消息；关联信息在
   autonomy observability 和 perceive-event audit 中可回查。
7. 现有鉴权、Path A wake delivery ledger、conversation gate、桌宠 WebSocket message contract
   不回归。删除或改写所有仍假设“Path B 必须同步 LLM 回复”的旧测试。

## 非目标

- 不改变普通 QQ/mobile/desktop owner chat，也不改工具 Path A/Path C 暴露面。
- 不重写 autonomy 模型、store、scheduler tick 或新增全局 EventBus。
- 不把桌宠重开变成强制发言；是否发言由现有 autonomy admission 决定。
- 不把 `last_seen`、原始客户端 body、角色名或用户私密状态写进新的可追踪文档/日志字段。

## 施工前必读

- `AGENTS.md`
- `docs/runtime-lifecycle.md`
- `docs/interaction-event-model.md`
- `docs/security_model.md`
- `docs/scheduler.md`
- `docs/channels.md`
- `docs/desktop-client-protocol.md`
- `cc-tasks/144-proactive-autonomy-signal-first-architecture.md`
- `cc-tasks/145-proactive-signal-adapters-and-merge.md`
- `cc-tasks/147-retire-direct-proactive-trigger-executors.md`
- `cc-tasks/148-fix-proactive-duplicate-signals-and-memory-repeat.md`
