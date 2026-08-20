# Brief 217 · Memory Event 身份链收口与 Soak 准入

> 状态：proposed；前置：Brief 214-216 / MER-09..11 已关闭；本工单只统一事件身份与入账关联，不创建 EventBus、不替换旧召回。  
> 目标：让一次入口事件、一次处理 turn、具体证据事件和派生记忆之间有可验证的身份链，然后用旁路观测和 soak 证明它不会破坏发送、隔离、幂等和旧记忆链。

## 一、开工前必读与硬边界

开工前必须读：`AGENTS.md`、`docs/memory.md`、`docs/interaction-event-model.md`、
`docs/runtime-lifecycle.md`、`docs/security_model.md`、`docs/dev-environment.md`、
`docs/three-repo-interface-catalog.md`。

必须先做只读调用链审计，覆盖 QQ、desktop、mobile、owner HTTP、scheduler、sensor、
tool loop、Dream、Stage、重试和进程重启。记录每条路径当前的 `uid/char_id/realm/source/channel/turn_id/event_id`。

本工单拍板以下边界：

- 不引入统一 EventBus、按 `kind` 的全局 dispatcher 或新的客户端协议。
- `PerceiveEvent` 仍是 Reality stimulus gate；`PerceptionEvent` 仍是感知数据合同；`WriteEnvelope` 仍只负责写入准入；`MemoryScope` 仍只负责隔离。
- Dream、Dream Stage、Reality Stage 继续使用各自生命周期。它们不因为拥有同名字段就进入 Reality evidence ledger。
- `event_id` 必须区分为 `ingress_event_id`（入口身份）和 `evidence_event_id`（账本中一条证据行的身份）。现有 `{turn_id}:user` / `{turn_id}:assistant` 作为 evidence ID 继续兼容。
- `turn_id` 只表示一次实际处理轮次；只有 signal-only stimulus、被 gate 拒绝的输入不得伪造 turn_id。
- 新开关默认关闭；旁路观测不得进入 prompt、recall、ranking、event_log、short_term、episodic、identity 或 storyline。
- 所有新落盘必须通过 `core/sandbox.get_paths()` / `DataPaths`，所有新观测必须有只读端点；不得记录原文、媒体正文、完整用户 ID、完整 event ID 或本机路径。

## 二、统一身份合同

新增小型内部 `EventContext`（建议 `core/event_context.py`，名称可按代码现状调整），不承担路由和业务决策，只承担冻结身份、来源和因果关系：

```text
schema_version
scope: uid + char_id + realm (+ world_id when applicable)
ingress_event_id       # 每个被接收的入口事件都有；由入口提供或系统生成
dedupe_key             # 入口幂等键
turn_id                # 只有真正创建 pipeline turn 后才有
causation_id           # 通常等于 ingress_event_id；派生 turn 指向其触发事件
source / channel / kind / actor
occurred_at / ingested_at
```

规则：

1. `receive_perceive_event()` 返回结果增加语义明确的 `ingress_event_id` 访问方式；`event_id` 旧字段保留为兼容别名，`existing_turn_id` 更正为 `existing_ingress_event_id`，旧名称在一个兼容周期内只读映射。
2. gate 接受后，调用方必须冻结 `EventContext.scope` 和 `ingress_event_id`，后续不得再次从 active character 解析角色。
3. 产生实际 LLM/assistant turn 时分配一次 `turn_id`，并将同一个 context 传到 `turn_sink → post_process_critical → capture_turn`；禁止在 post-process 再生成第二个逻辑 turn 身份。
4. ledger 中的 user/assistant evidence ID 由 `turn_id` 派生；trigger assistant 只有 assistant evidence。signal-only stimulus 仅保留入口审计，不生成假的 assistant evidence。
5. `source_event_ids`、`causation_id` 和确定性 relation 只能引用当前冻结 scope 内已存在的 evidence ID；模型 proposal 仍不能写入确定性边。
6. `uid + char_id + realm (+ world_id)` 不一致、Dream/Reality 混用、入口事件与 turn 关系缺失时 fail-closed 记录该次身份错误，并 fail-open 保留现有发送路径；不得静默改写成默认角色或默认 realm。

## 三、施工分段（必须独立提交）

### 217-A：Context 类型与入口适配

涉及：`core/event_context.py`、`core/perceive_event.py`、`core/memory/scope.py`、
`core/write_envelope.py` 及各入口 adapter。

- 实现不可变/冻结的 `EventContext` 与构造、校验、序列化 helper。
- 为 user chat、scheduler、sensor、desktop wake、mobile/companion 适配入口；保留各入口原有 gate、权限和 fanout 语义。
- 明确 signal-only、gate rejected、实际 turn 三种 disposition，避免把入口事件误叫 turn。
- 添加上下文校验失败的 content-free runtime signal。

### 217-B：turn_sink 与证据入账收口

涉及：`core/turn_sink.py`、`core/pipeline.py`、`core/memory/fixation_pipeline.py`、
`core/memory/event_store.py`、`core/memory/lineage.py`。

- 新增 `commit_turn_evidence(context, ...)`（或等价内部 sink），由一个入口完成 user/assistant evidence 双写、确定性关系和 topic 写入。
- `capture_turn()` 继续兼容旧调用，但不得绕过 context；旧调用缺 context 时只允许明确的兼容适配，不得猜角色、realm 或 causation。
- 为 event ledger 增加必要的 nullable provenance 字段/迁移；迁移必须走 `event_store.initialize()`，不能在发送关键路径执行 DDL。
- 让入口 `ingress_event_id` 能在账本和 lineage 查询中被追溯，但不把入口 metadata 当成用户原文。
- 保持现有 fail-open 发送语义、250ms SQLite busy 上限和 duplicate 幂等行为。

### 217-C：旁路 trace、控制面与观测

涉及：`core/data_paths.py`、`core/memory/...`（trace accessor）、`admin/routers/`、
`docs/feature-control-surface.md`、`docs/three-repo-interface-catalog.md`、
`docs/known-issues.md`。

- 增加默认关闭的 `event_context_observer`（建议只读/热切换）及 effective state：`disabled / observe / enforcing`。本工单生产默认只能是 `observe` 或 `disabled`，不得默认 enforcing。
- 写入 content-free context trace：stage、disposition、scope match、causation match、duplicate、orphan、latency bucket、error code、source/realm aggregate；不写原文和完整 ID。
- 提供 `GET /observability/event-context`，使用现有 `state.read`，返回聚合计数、延迟、失败、重启恢复和最近状态；空数据必须显示“未运行”。
- 管理面只展示 desired/effective/route/run，不新增桌面或手机设置；跨仓总账明确为 backend-only。

### 217-D：Enforcing 灰度闸门

只有 217-A/B/C 测试通过且完成一次短 soak 后才可施工。

- 按 `uid`、`char_id` 灰度启用 context 校验；enforcing 只阻止身份不完整/跨 scope 写入，不改变正常 prompt 和旧召回。
- 保留一键回退到 observe/disabled；回退后旧 `capture_turn`、event ledger 双写和发送路径仍可运行。
- 不在本工单把 Memory Event ledger 宣布为唯一事实源；该决定需要独立工单和长期数据证明。

## 四、Soak 计划与退出条件

需要 soak，而且是本工单的验收门，不是上线后的可选观察。分三层：

### S0：离线/测试回放（施工门）

使用脱敏 fixture 和故障注入覆盖：普通 user turn、trigger、sensor、desktop wake、
mobile/companion、tool loop、媒体、重复请求、乱序 append、字符切换竞态、SQLite busy、
进程在 critical 写入前后重启、Dream/Stage 并行存在。要求所有 disposition 可解释，旧路径结果与基线一致。

### S1：短 soak（enforcing 前）

测试环境运行至少 72 小时，或完成 200 个 canonical turns 与 100 个 stimulus（取较晚者）。
至少包含两种通道、两种角色 scope、一次重启恢复和一次 ledger 暂时不可用。S1 期间 enforcing 只在测试 scope 开启。

### S2：生产样本 soak（正式准入）

生产默认 `observe`，按一个明确 `uid + char_id` 小范围灰度，至少连续 7 天且达到 500 个 canonical turns；
建议目标为 14 天/1000 turns。期间禁止打开 shadow recall 或 proposer 作为联动变量，避免无法归因。

退出条件：

- 适用 turn 的 context 贯通率 ≥ 99.99%；`scope_mismatch`、`realm_mismatch`、跨角色/跨 Dream-Reality 污染为 0。
- 新路径 orphan evidence、重复 turn、无 disposition 的 ingress 均为 0；可解释的客户端重试必须落为 duplicate，而不是第二个 turn。
- 进程重启后恢复率 100%，不重复发送、不重复写证据；冲突和 schema mismatch 必须可观测且不阻塞旧发送。
- send 前 critical 段 p95 相对基线增加 ≤5ms、p99 增加 ≤20ms，且单次等待不超过既有 250ms SQLite 上限；超标即回退 observe/disabled。
- `short_term/event_log/mid_term/episodic/storyline` 内容、prompt layers、旧 recall 命中与 shadow 关闭时的行为和基线无差异。
- 观测端点无原文、完整用户 ID、完整 event ID、媒体正文或本机路径泄漏；客户端无新增协议依赖。

任一硬红线失败，停止扩大灰度，回退到 `observe` 或 `disabled`，保留 trace 和故障摘要，修复后从 S1 重新累计；不得用平均指标覆盖单个跨 scope 污染。

## 五、测试

新增或更新专项测试，至少包括：

- `tests/test_event_context_contract.py`：字段、冻结 scope、ID 派生、序列化与 fail-closed。
- `tests/test_event_context_propagation.py`：各入口到 turn_sink/capture_turn 的贯通和 signal-only 分支。
- `tests/test_event_context_scope_isolation.py`：uid/char/realm/world 交叉污染、Dream/Stage 隔离。
- `tests/test_event_context_idempotency.py`：重试、乱序、重复 append、进程恢复。
- `tests/test_event_context_observability.py`：content-free trace、权限、空数据和延迟聚合。
- 现有 Memory Event、turn sink、trigger boundary、short-term、Dream/Stage isolation 回归。

按 `docs/dev-environment.md` 使用 Python 3.14 本机 pytest 入口时，命令统一为：

```text
pytest -n auto tests/test_event_context_*.py tests/test_memory_event_store.py tests/test_perceive_event.py
```

部分改动优先 `pytest --testmon` 或指定路径；不得用不带 `-n` 的全量串行测试。

## 六、拍板与不做什么

- 拍板：统一的是身份链和证据 sink，不是所有入口的业务流程；`DataPaths` 不改职责。
- 拍板：入口事件、处理 turn、证据事件使用三个明确命名空间；不再用一个 `event_id` 同时表示三者。
- 拍板：observe 默认关闭/可灰度，enforcing 必须经过 S1；S2 至少 7 天/500 turns。
- 不做：不自动迁移历史 Markdown，不改旧召回排序，不打开 shadow/proposer，不接受模型关系候选，不改 Dream/Stage 协议，不新增客户端 UI。
- 不做：不删除现有 `_append_event_ledger`、`capture_turn` 兼容入口，除非另有删除工单并完成独立迁移和测试清理。

每个子段测试通过、差异检查完成后立即独立 Git commit；完成 S2 后另提交 soak 报告，内容只含聚合指标、失败码、版本和回退记录，不含原文或敏感身份值。
