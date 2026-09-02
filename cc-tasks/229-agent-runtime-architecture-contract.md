# Brief 229：Agent Runtime 总体架构与边界合同

> 状态：proposal；前置：Brief 217 EventContext soak 继续按原计划进行；本工单只冻结新架构，不改运行代码。

## 目标

为“角色可以长期执行任务、使用本地能力并在需要时主动行动”建立统一架构，避免继续向
`tool_dispatcher`、`scheduler`、`autonomy` 和 `self_management` 分别追加能力。

## 当前代码事实（开工前必须复核）

- `core/event_context.py` 只承载 Reality ingress、turn 和 evidence 身份，不是通用任务信封。
- `core/event_context_observer.py` 是 content-free 的身份链旁路观测；`enforcing` 在代码中仍按
  soak gate 处理为 observe，不得被新 Runtime 当作已全面 enforcing。
- `core/scheduler/gating.py` 将 trigger 分为 `migrated`、`maintenance-only`、`retired`、`active`。
- `core/autonomy` 已拥有短时 opportunity/job/lease/runner，但它的职责是主动性评估，不是通用长期任务管理。
- `inner_diary_write` 在 23 点窗口静默生成角色日记；`daily_journal` 是可能产生用户可见消息的主动 signal。
- `scheduler._pipeline_send` 对已迁移 trigger 只保留兼容 signal 边界，不能恢复为第二条发言路径。

## 目标分层

```text
Clock / Trigger Plane
  -> 产生 due signal 或创建任务，不生成台词

Task Plane
  -> task_id、状态、lease、TTL、取消、重试、恢复、receipt

Agent Plane
  -> 需要 LLM 规划、工具选择或 authored material 生成时才运行

Capability Plane
  -> workspace / process / browser / scheduler / memory / MCP 等适配器

Interaction Plane
  -> 只有用户可见 Reality 消息才创建新的 EventContext 并进入 turn_sink

Dream Runtime
  -> 独立 realm、独立状态和能力集合；不得访问 Reality Runtime
```

## 硬边界

1. 不引入 universal EventBus，不把 `EventContext` 扩展成全系统事件总线。
2. `task_id`、`ingress_event_id`、`turn_id` 是三个不同命名空间，不能互相复用。
3. Task receipt、worker 日志和能力观测不写 Memory Event ledger、`short_term`、`event_log` 或长期记忆。
4. 任务可以保存 bounded `causation_ref`，但它只是来源引用，不是 evidence。
5. 任务完成后若要通知用户，必须产生新的 Reality ingress 和新的 turn；不得复用创建任务的旧 turn。
6. Dream 默认零 Reality 能力，不能创建 Reality task、读取 Reality task store 或访问浏览器登录态。
7. Agent Runtime 共享代码可以复用锁、序列化和资源限制 helper，但不得共享 Reality/Dream 运行态和记忆写入器。
8. 远程部署时本地 OS capability 必须整体不可用，不能把服务端机器当作用户桌面。

## 迁移原则

- 旧 trigger 文件先作为 adapter 保留，逐项迁移后再删除；不一次性重写 scheduler。
- `migrated` trigger 变成 signal producer；`maintenance-only` 变成 Task Plane worker；`retired` executor 不恢复。
- `autonomy` 先作为 Agent Plane evaluator 适配器，后续再决定是否将其 job store 迁入通用 Task Plane。
- 228 资料库作为一个 `memory/document` capability 接入，不改变既有记忆固化流程。

## 验收

- 有一张架构映射表，列出每个现有 scheduler trigger、autonomy job、tool 和 store 的目标归属。
- 有明确的 EventContext 非耦合证明：新 task 生命周期不会生成 evidence，用户通知会创建新 ingress/turn。
- 有 Reality/Dream 负向测试设计，证明 Dream 不能读写 Reality task 或 capability。
- 本工单不新增客户端协议，不改变 217 soak 的采样和指标语义。

