# 145 主动信号适配器与候选合并

## 目标

把现有时间节点、传感器、记忆、重启和未完成话题转换成结构化候选信号，交给 `core.autonomy` 统一评估。

## 建议契约

新增轻量 `ProactiveSignal`（名称可按实现调整），至少包含：

- `signal_id` / `source` / `created_at` / `expires_at`；
- `reason`：care、unfinished_topic、memory_reactivation、routine、state_change、curiosity 等；
- `evidence`：只放可验证事实，不放已经写好的台词；
- `priority` / `urgency` / `confidence`；
- `memory_query` 或明确的记忆 key；
- `suggested_action`：silent、message、question、suggestion、tool_then_talk。

## 迁移对象

- 午间碎碎念：降为低权重 `routine` 信号。
- 早安/晚安：降为时间背景信号，不再直接生成固定问候。
- 心率提醒：产出状态变化信号，携带测量时间、变化方向和可信度；不直接写提醒台词。
- `spontaneous_recall`：产出带 memory key 的 `memory_reactivation` 信号。
- `topic_followup`：产出带未完成主题和最近提及时间的 `unfinished_topic` 信号。
- `desktop_wake`：产出 reopen/session 信号，携带系统计算的离线时长。

## 合并规则

同一 opportunity 窗口内按 reason 和 memory key 去重；多个弱信号可合并为一个候选，紧急信号可提升优先级但不能绕过 dream/user-active/预算闸门。

## 验收

- 单次主动评估最多生成一个用户可见主动回合。
- 同一时间的早安、心率、午间信号不会各自发言。
- 过期信号不会在重启后无条件补发。
- 所有信号均可在 autonomy run 观测记录中回放。
