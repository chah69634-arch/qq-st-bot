# 147 迁移并退役主动触发器直发路径

## 目标

完成从“触发器直接发言”到“触发器提供信号、autonomy 统一决策”的迁移，消除双发和机械模板。

## 实施步骤

1. 为每个交互型触发器登记 signal adapter 和迁移状态：migrated、maintenance-only、retired。
2. 将 `morning_greeting`、`good_night`、午间碎碎念、普通心率提醒、固定 random message 等直发 executor 改为 signal producer。
3. 保留 `diary_inject`、memory janitor、event-log salvage、hidden-state decay 等非 assistant-turn 维护任务，不接入 talk_owner。
4. 生日、严重健康异常等高优先级来源先保留独立候选，但仍经过统一 autonomy admission；只有明确的安全/用户约束理由才允许提升 urgency。
5. 删除或封存旧 `_pipeline_send()` 发言分支，清理 scheduler 面板中的“手动直接发言”入口，改成“排队一次 autonomy opportunity”。
6. 为迁移期增加双路径保护：同一 signal/opportunity correlation id 只能产生一次 talk_owner 发送。

## 验收

- 普通主动消息只有一个用户可见出口：`talk_gate.send()` / `talk_owner`。
- 旧触发器不会绕过 autonomy ledger、talk gate、conversation gate 或用户活跃取消。
- 早安/晚安/午间/心率在观测面显示为信号与最终决策，而不是独立 assistant trigger turn。
- 删除无引用 legacy executor 及其僵尸测试；保留维护型任务的现有测试。
