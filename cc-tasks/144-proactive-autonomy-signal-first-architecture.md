# 144 主动性架构：Signal-first Autonomy

## 决策

将现有 `core.autonomy` 作为统一主动性执行底座。调度器和触发器不再直接决定台词并发送；它们只产生候选信号或维护状态。自主运行层负责一次完整的主动机会评估：是否值得打扰、应该围绕什么主题、是否需要召回记忆、是否需要工具、是否发送最终消息。

触发器与工具职责严格分离：

- trigger/sensor：系统侧事实和候选理由来源，角色不可调用；
- autonomy job：系统排队并执行一次内部决策；
- tool：角色在 autonomy job 内可使用的受限能力；
- `talk_owner`：唯一允许把主动结果送入用户对话的出口。

## 当前底座

- `core/autonomy/models.py` 已有 Job、Run、Disposition。
- `core/autonomy/runner.py` 已有内部 tool loop、`talk_owner`、沉默结束、预算和 user-active 取消。
- `core/autonomy/policy.py` 已有自主工具安全 allowlist。
- `core/autonomy/store.py` 已有 durable job/source/run 状态。
- `core/scheduler/loop.py` 只负责 tick 消费 autonomy job。

## 需要补齐的能力

1. 候选信号必须携带事实、理由、优先级、时效、记忆锚点和建议行动类型，不能只传 `source="interval"`。
2. 一次 tick 内多个信号必须合并为一个 autonomy opportunity，而不是各自发言。
3. “不说话”必须是一等结果，且可观测为什么沉默。
4. 主动生成必须使用统一的记忆召回和现实时间事实；模型不能从“早安/中午”自行推断用户状态。
5. 旧直发触发器迁移后，删除或封存其 assistant-turn executor，避免双路径发送。

## 非目标

- 本工单不直接实现早安、心率、午间等具体触发器迁移。
- 不把 trigger 暴露为模型工具。
- 不引入全局 EventBus；继续复用 proposer registry、autonomy store、turn sink 和现有 gates。

## 验收

- 有一份 versioned signal/opportunity 契约，明确 source、evidence、reason、expiry、priority、memory_query、action_mode。
- autonomy 是主动消息的唯一发言出口；旧 scheduler 直发路径有迁移清单。
- 设计文档和观测接口能区分“未评估、评估后沉默、工具完成但不发言、发言成功、被用户活动取消”。
