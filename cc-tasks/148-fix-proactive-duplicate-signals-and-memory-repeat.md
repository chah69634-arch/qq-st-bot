# 148 修复主动信号双生产者与记忆重复回忆

## 背景

Signal-first autonomy 已经成为主动消息的统一执行底座，但长时间运行审查发现两个返修点：

1. 时间背景信号存在两个生产者；旧迁移触发器通过 `emit_trigger_signal()` 默认产生 `TALK` 候选，autonomy runner 又直接生成 `routine` 候选。
2. autonomy tick 每次都选择 strength 最高的 episodic 记忆，没有接入主动回忆冷却，可能重复围绕同一条记忆发言。

## 实施范围

### A. 时间/例行信号单一生产者

- 明确 morning/night/midday/random 等例行信号的唯一生产位置。
- 迁移后的旧 `_check_*()` 只能提交候选事实，不得默认把低权重 routine 提升为 `TALK`。
- runner 不得绕过旧触发器配置，或者新增 autonomy 自己的等价配置；关闭某个例行来源后，该来源不得继续产生候选。
- 同一时间窗口内同语义候选应使用稳定 dedupe key，最终 opportunity 只保留一份事实集合。
- 保持高优先级健康/安全来源的明确 urgency 语义，但仍经过统一 autonomy admission。

### B. episodic 主动回忆冷却

- 为 `memory_reactivation` 候选增加稳定 memory key 的冷却/已评估状态。
- 复用现有 episodic recall ledger/helper（如 `is_recently_recalled` / `mark_memory_recalled`），不要另造无法观测的模块级缓存。
- 明确标记时机：至少区分“候选已评估”“工具/记忆已读取”“实际主动发言成功”；失败或静默不应伪装成成功回忆。
- 仍允许当前对话或明确新信号在冷却期内通过 anchored 方式重新召回，但必须有新的证据或用户上下文。

### C. 文档和测试

- 更新 `docs/feature-control-surface.md`，说明 autonomy 关闭时 migrated trigger 的实际行为。
- 更新 `docs/assistant-turn-sink.md`，把普通 scheduler 触发器改为 signal/autonomy 路径现状。
- 增加组合测试：
  - morning scheduler signal + runner routine signal 只形成一个不强制 TALK 的 opportunity；
  - 例行来源关闭后 runner 不再生成该来源候选；
  - 相同 episodic memory 在冷却期内不重复成为主动候选；
  - 新证据或明确 anchored query 可重新激活；
  - 现有 `talk_owner` 唯一出口和高优先级 admission 不回归。

## 验收

- 例行时间点不会仅因时钟到点就强制产生主动发言。
- 同一例行事实不会被两个生产者重复提交。
- 长时间 autonomy 运行不会反复选择同一条最高强度记忆。
- 所有新增状态可通过现有 autonomy opportunity/run 观测接口解释。
- 相关测试使用 `pytest -n auto` 运行并通过。

## 不在范围内

- 不重做 Signal-first autonomy 总体架构。
- 不新增主动消息类型或新的触发器。
- 不改变普通 owner chat tool loop。
