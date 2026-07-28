# Wake Bridge P0.5：Durable External Stimulus Inbox

Wake Bridge 是论坛等外部来源进入既有主动唤醒链的薄适配层。P0.5 增加的是一个小型、持久化的待处理收件箱；它不是第二个 scheduler、通用 EventBus、聊天历史或消息队列。

```text
provider adapter / POST ingress
  -> durable receipt inbox
  -> existing scheduler tick drain
  -> TriggerProposal(external_forum_message)
  -> gating._decide() -> execute_prompt()
  -> _pipeline_send() -> receive_perceive_event()
  -> conversation lock -> LLM -> turn_sink
```

收件箱从不直接调用 LLM、`turn_sink` 或 conversation lock，也不绕过 Dream Guard、ProactiveLedger、全局间隔、每日预算或既有 gate。

## receipt dedupe 与 execution disposition

两件事必须分开：

* **source receipt dedupe**：`{provider, external_id}` 的稳定键已被可靠接收后，重复投递返回 `duplicate`，不创建副本、不重置 attempts、不延长 TTL、不重新触发 LLM。随机 `event_id` 不参与此判断。
* **execution disposition**：该已接收事件当前是否已被消费。状态为 `pending`、`processing`、`consumed`、`expired`、`rejected`。

收到事件时先原子写入 `pending`，再允许尝试执行。因此 owner 正在聊天、DND/quiet hours、间隔或预算暂时不足、Dream active、Dream Guard 不确定、暂时性执行错误或 scheduler 暂不可用，都不会把 receipt 当成已消费：记录仍为 `pending`，并带有下一次尝试时间。

只有以下情形终止事件：实际主动链成功发送 assistant turn 后为 `consumed`；TTL 到期为 `expired`；记录无法满足固定契约等永久无效情形为 `rejected`。

## 持久化内容与隔离

状态使用 `DataPaths` / sandbox 的原子写入，路径为：

```text
runtime/wake_bridge/{char_id}/{uid}/{provider}.json
```

每条 inbox 记录保存 provider、external id、stable event key、接收/发生时间、清洗且有长度上限的标题与摘要、canonical URL、作者标签、原文 hash、status、attempts、last/next attempt、last disposition 和 expires time。不会保存完整 HTTP 请求体、请求头、cookie、webhook secret 或未受限的论坛原文；观测接口也不返回摘要、external id、hash 或 cursor。

外部摘要仍是明确标注的低信任 reality stimulus：不能覆盖 uid、char_id、realm、kind、trust 或权限，不能升级为 tool/activity，也不会写 ordinary short-term、user message、trigger stub 或长期记忆。只有真正生成的 assistant turn 才走既有 `turn_sink` 行为。

## cursor 提交与 provider adapter

`ForumSource.fetch_since(cursor)` 返回规范化事件与候选 cursor。`WakeBridge.poll_source()` 对每一条先完成 durable receipt：新事件必须已是 `pending`，重复 receipt 已存在于任一持久状态；若某条事件 malformed 或持久化失败，整个批次不提交新 cursor。只有所有本批事件已可靠落入 `pending` / 既有 `consumed` / 既有 `rejected` 时，才原子推进 cursor。

新增 provider adapter 只应负责认证、分页、响应解析和把结果映射为 `ExternalStimulus`（或同字段 mapping），随后调用 `poll_source()`。本轮没有接入具体论坛 API，也没有自动回帖、私信、点赞或发帖能力。

## drain、重试和崩溃恢复

既有 scheduler 的 60 秒 tick 调用 `WakeBridge.drain_due()`；没有第二个循环。每个 tick 有全局小上限，且每个 `{provider, uid, char_id}` scope 至多尝试一条，避免单一 provider 占满 tick。当前不做复杂合并：每次执行一条 event，后续可在不改变 disposition 契约的前提下增加合并 proposal。

drain 会先在原子状态写入中把记录标为 `processing`，增加 attempts，并持有短 lease。并发 drain 不能同时 claim 同一记录。进程崩溃后，过期 lease 变回 `pending`；此前的 claim 已计入 attempts，下一次正常重试会继续使用有界退避。retry delay 对 gate 原因采用保守等待，对 Dream/Guard 和临时执行异常采用有界指数退避；TTL 是最终边界。

成功执行的唯一判据是既有主动链确认发送了 assistant turn。gate 拒绝、Dream Guard `blocked_dream`、perceive 去重窗口或无回复都回到 `pending`，绝不错误标记 consumed。

## HTTP ingress 与可观测性

`POST /integrations/forum/events` 接收单条标准化对象或 `{ "events": [...] }`（最多 20 条），需要 `integration.write`。鉴权在接收前发生；uid 必须为配置 owner，char_id 必须为当前 active character。

`GET /observability/wake-bridge` 需要既有 `state.read`。它可以按 uid、char_id、provider 筛选，并仅返回 scope 与聚合指标：`pending_count`、`processing_count`、`consumed_count`、`expired_count`、`rejected_count`、`oldest_pending_at`、`consecutive_failures`、`last_success_at`、`last_error_at`（以及不泄露值的 `has_cursor`）。日志同样只记录 provider 和 hash，不记录正文、secret 或原始请求体。
