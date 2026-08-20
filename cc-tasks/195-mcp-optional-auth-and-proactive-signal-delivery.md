# Brief 195：MCP 可选鉴权与主动唤醒 signal-first 交付修复

## 状态

`ready` / backend + admin UI implementation

## 背景与已确认根因

本工单收口三个表象问题，但不增加新的主动消息出口。

1. MCP 管理页把 `Authorization: Bearer ${MCP_TOKEN}` 作为新连接的默认 header。无鉴权 server 本可由后端空 headers 正常连接，却会因为前端提交该模板、环境变量未设置而 fail-closed。
2. `festival` 与 `period_reminder` 已列入 migrated trigger；生产模式禁止 legacy `_check_* -> _pipeline_send()` 直发，native proposal pass 又主要用于 shadow audit。普通 tick winner 没有统一转成持久化 autonomy signal，因此候选可能只被观测而不会进入真正的 autonomy opportunity。
3. 当前 festival 表没有农历换算和七夕条目。七夕当天不会产生 proposal，这与后续发送 gate 无关。
4. 现场反馈 autonomy 已运行但从未出现 `talk_sent`。当前没有证据证明这是合理的模型静默选择、候选未入队、admission 阻断、talk gate 阻断，还是门槛组合过严。不得在没有 disposition 分布和端到端测试前直接提高“概率”或绕过 gate。

## 唯一发送边界

修复后的用户可见主动消息仍只能走：

```text
trigger / sensor / scheduler fact
  -> autonomy signal store
  -> autonomy runner merge + admission
  -> model explicitly calls talk_owner
  -> talk_gate.send()
  -> record_assistant_turn()
  -> channel fanout
```

禁止：

- 恢复 `festival._check_festival()`、`period._check_period()` 的生产直发；
- 从 proposer、signal adapter 或 scheduler loop 直接调用 `_pipeline_send()`、`talk_gate.send()`、channel broadcast；
- 为 festival、period 或 MCP 新建独立发送 worker/outlet；
- 用 trigger prompt 代替结构化 factual evidence 注入 autonomy；
- 为提高开口率绕过 DND、Dream、conversation lock、用户活跃取消、每日预算、全局冷却或 turn sink。

## 开工前必读

1. `AGENTS.md`
2. `docs/runtime-lifecycle.md`
3. `docs/interaction-event-model.md`
4. `docs/security_model.md`
5. `docs/tools.md`
6. `docs/scheduler.md`
7. `docs/autonomy.md`
8. `docs/feature-control-surface.md`
9. `docs/dev-environment.md`

## 子任务 A：MCP 无鉴权连接

1. 管理页新建 MCP server 时 headers 默认必须为空；“请求头（可选）”与实际提交一致。
2. 如保留 Bearer 快捷能力，应由显式操作添加 `Authorization: Bearer ${ENV_VAR}`，不能默认提交。
3. 后端继续允许 `{}` / 无 headers；显式 `${ENV_VAR}` 缺失仍 fail-closed，不降级为发送字面模板或空 token。
4. UI 不回显展开后的 secret，不把 token 写入日志、文档或 URL。
5. 修改 `admin/static/js/mcp.js` 或 page fragment 时按静态资源缓存规则更新版本。

## 子任务 B：统一 proposal -> autonomy signal

1. 为 tick 型 migrated proposal 建立一个通用、可测试的 factual adapter。只有通过现有 scheduler proposal gating 选中的 winner 才能入队；不得让所有候选绕过 winner 竞争并各自建 job。
2. adapter 只携带 trigger name、结构化 evidence、priority/urgency、TTL、可选 memory query 与 action mode，不携带旧 assistant prompt。
3. `festival` evidence 至少包含稳定 festival key、现实日期与 calendar source；`period_reminder` evidence 至少包含阶段（current/upcoming）和有界 days elapsed，不包含不必要的健康正文。
4. 入队后由同一 tick 的 `autonomy.runner.tick()` 合并和消费；去重键、TTL、Dream retry 与 disposition 继续复用现有 autonomy store 契约。
5. `dream_exit` 的专用 lifecycle/correlation 语义不得被通用化丢失；如走同一 helper，必须保留其 `dream_id` 和现有测试。
6. 修正文档与代码偏差：明确 compatibility `_pipeline_send` 当前真实行为，或实现文档承诺的只入队兼容边界；无论选择哪种，生产中不得存在第二条 user-visible path。

## 子任务 C：节日日历与七夕

1. 为中国农历节日采用成熟、已有依赖可承受的历法实现；禁止用年度硬编码日期表冒充长期支持。
2. 首批至少覆盖七夕，并明确时区以 scheduler 所在本地现实日期为准；农历日期转换失败时 fail-closed，只影响该候选。
3. 保留角色卡私人纪念日与现有公历节日优先级，并为同日冲突定义确定性 winner/合并规则，避免同一 tick 多次发言。
4. 节日只产生 factual signal；具体措辞由 autonomy 在角色上下文中决定。

## 子任务 D：零主动发言诊断与门槛校准

先通过现有只读观测与补充的聚合视图回答以下漏斗，不读取或返回用户正文：

```text
producer matched
  -> signal queued
  -> opportunity created
  -> admission allowed
  -> talk_owner schema available
  -> model selected talk_owner
  -> talk gate allowed
  -> turn sink delivered
```

1. 按 trigger/source 和 disposition 聚合近 24h/7d 的数量，区分 `no candidate`、`expired`、`blocked_user_active`、`daily budget`、`minimum interval`、`talk unavailable`、`evaluated_silent`、`tools only`、`talk gate rejected`、`talk_sent`。
2. 复用或扩展 `/observability/autonomy-opportunities`、`/admin/autonomy/effective-state` 与 runs 观测；若新增落盘字段，必须同单提供 `state.read` 只读投影。
3. 不新增一个不可解释的全局随机概率。若数据证明模型在高价值、明确 `action_mode=talk` 的有效 signal 上长期静默，优先调整 signal 语义、prompt 决策准则或 source-specific policy，并保留静默选项。
4. 必须给出校准目标和安全上限，例如按 source 的候选到 talk 转化率、每日 talk 上限和连续未回复上限；不能以“测试能发一条”为生产行为完成。
5. 管理面应能看到当前最先阻断原因和漏斗计数，不要求操作者拼多个日志猜测。

## 三面闭环

1. Backend：admin 设置、effective state、autonomy opportunity/run、trigger catalog 与 MCP runtime 状态一致；scope 不降低。
2. Desktop/admin UI：MCP 可选 headers 体验与 autonomy 漏斗/阻断原因可见；若桌面客户端消费 scheduler 设置，核对现有能力检查与降级提示。
3. Mobile：不新增协议字段时明确无改动；若主动消息 payload、设置或观测契约变化，核对 mobile polling/relay/fanout 并同步三仓接口总账。
4. 调用链：核对 trigger -> proposal -> winner -> signal -> opportunity -> admission -> `talk_owner` -> talk gate -> sink -> fanout 的 correlation、dedupe、TTL、锁、预算和失败终态。

## 测试

至少覆盖：

1. MCP 空 headers 可通过 test/import/reload 路径；显式 Bearer env 模板仍可用；缺失 env 稳定报错。
2. MCP 管理页初始 header editor 为空，显式添加/删除 header 后 payload 正确；静态缓存版本已更新。
3. festival 与 period 在命中条件时，各自产生一个 factual signal；未命中、关闭开关、缺 owner/period date 时不入队。
4. 同一 tick 多个 migrated proposal 仍只按现有 winner 规则入队，不产生并行主动发送 job。
5. 七夕在跨年份已知样例上正确识别；相邻日期不误触发；时区和转换失败行为确定。
6. 端到端测试证明 trigger signal 经 runner 后只有显式 `talk_owner` 才能进入 sink，旧 `_pipeline_send` 与 channel 直发均未调用。
7. 分别覆盖 admission 阻断、model 静默、talk gate 阻断和成功 `talk_sent`，观测漏斗能准确区分。
8. DND、Dream、用户活跃、conversation queue/lock、预算、冷却、连续未回复、correlation 去重与无可用 channel 的原路径回归。
9. `period_date_missing` 继续可观测且不泄露健康内容；festival/period evidence 与 prompt snapshot 均通过敏感字段审计。

按 `docs/dev-environment.md` 使用相关路径测试和 `pytest -n auto`；不因本工单默认跑无关全量。

## 文档同步

实现时同步：

- `docs/tools.md`
- `docs/scheduler.md`
- `docs/autonomy.md`
- `docs/feature-control-surface.md`
- `docs/three-repo-interface-catalog.md`
- `docs/known-issues.md`（未完成的客户端或生产校准项标 `open` / `observe`）

## 验收

- 无鉴权 MCP server 不填写任何 header 即可连接；需要鉴权的 server 仍显式、安全地配置 Bearer。
- 七夕与生理期候选能进入 durable autonomy signal/opportunity，不直接生成台词或发送消息。
- 用户可见主动消息仍只有 `talk_owner -> talk_gate -> turn_sink` 一个出口。
- 管理面能回答“为什么最近没有主动说话”，并区分没有候选、候选未入队、gate 阻断和模型主动静默。
- 至少一个隔离端到端用例达到 `talk_sent`，同时所有硬安全门与预算约束保持有效。
- 相关测试、差异检查、文档与三面闭环完成后独立提交。
