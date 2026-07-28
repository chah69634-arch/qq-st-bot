# Wake Bridge P0

Wake Bridge 位于 `core/wake_bridge.py`，是论坛等外部来源进入现有主动唤醒链之前的薄适配层：

```text
forum adapter / POST ingress
  -> ExternalStimulus normalization + persistent source dedupe
  -> TriggerProposal(external_forum_message)
  -> gating._decide() -> execution.execute_prompt()
  -> scheduler._pipeline_send() -> receive_perceive_event()
  -> conversation_lock -> LLM -> turn_sink
```

它不是 scheduler、EventBus 或消息队列：不挑选其他 trigger、不直接调用 LLM 或 `turn_sink`，也不绕过
gating、Dream Guard、ProactiveLedger、全局间隔、每日预算或 conversation lock。活跃 owner 对话、DND、
budget 等拒绝会得到 `gated`；Dream active 或状态不确定会得到 fail-closed 的 `blocked_dream`。

## 外部 stimulus 契约

`ExternalStimulus` 固定为 reality / stimulus / oneshot 语义，固定 `trust="low_trust"` 和
`source="forum"`。它需要 `provider`、`external_id`、`uid`、`char_id`、`occurred_at`，并可带受限长度的
标题、作者标签、链接、摘要和 JSON-safe 小 metadata。`provider + external_id` 是唯一稳定去重依据；随机
`event_id` 不参与来源去重。

正文会清除控制字符并截断，且只作为本轮 prompt 中明确标为“外部论坛事件摘要”的不可信数据。它不是
用户消息、system/developer instruction、tool 权限或 activity 指令。正文不会写入 Wake Bridge 状态、
来源审计或 ordinary short-term；常规 trigger 产生的 assistant reply 仍沿用既有 turn sink 语义。

## HTTP ingress 与鉴权

`POST /integrations/forum/events` 接收单条标准化对象，或 `{ "events": [...] }`（最多 20 条）。它要求
Bearer token 的 `integration.write` scope；管理员可通过 token 管理 API 建立 `integration` profile token。
鉴权发生在处理前，因此 401/403 不创建状态、不触发 LLM。

请求中的 `realm`、`kind`、`source`、`trust`、tool/activity 字段不参与执行，也不能覆盖 uid/char scope。
uid 必须是配置的 owner，char_id 必须是当前 active character。每条结果为 `accepted`、`duplicate`、
`gated`、`blocked_dream`、`malformed` 或 `source_error`。

## 恢复、审计与 adapter

状态按 `runtime/wake_bridge/{char_id}/{uid}/{provider}.json` 隔离（经 `DataPaths` / sandbox 管理），
原子保存 `last_cursor`、近期 provider/external-id 去重哈希、最近成功/错误时间和连续失败数。重启后旧事件
不会再次唤醒。现有 trigger audit 只补充 provider、external-id hash、raw-content hash；不存原文、token、
cookie 或完整请求。

只读运维入口 `GET /observability/wake-bridge`（`state.read`）只展示 scope、cursor 是否存在、
去重计数和最近成功/错误状态；不会返回 cursor、external id、正文或 secret。

未来只读来源实现 `ForumSource.provider` 和 `fetch_since(cursor) -> (events, next_cursor)`，然后交给
`WakeBridge.poll_source()`。provider API、鉴权、分页和响应解析必须留在 adapter 内。P0 的 `FakeForumSource`
只用于测试；本轮没有接入具体论坛 API，也没有自动回帖、私信、点赞或发帖能力。
