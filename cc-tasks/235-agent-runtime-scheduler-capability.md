# Brief 235：原生闹钟与用户长期任务

> 状态：proposal；前置：230、231；先实现原生 scheduler capability，再考虑让 Agent 生成程序替代它。

## 目标

提供一次性闹钟、周期任务和取消/查询能力，让“定闹钟”不需要任意代码执行。

## 现有代码事实

`core/tools/reminder.py` 已有 owner scoped reminder 文件、创建、到期读取和完成标记；scheduler loop 的
`_check_reminders()` 仍带有旧的直接提醒路径，需在迁移时保留用户可见语义但统一任务生命周期。

## 目标行为

```text
agent/user request -> schedule task -> due task -> delivery signal -> optional autonomy decision
```

任务内容和时间由结构化字段承载；每个 task 有稳定 ID、时区、重复规则、下一次触发时间、TTL 和取消状态。
到点后是否立即通知，应由任务类型明确决定：用户明确要求的闹钟可以直接进入受控 delivery；角色主动提醒仍须
经过既有 autonomy/talk gate。

## 验收

- 重复请求幂等；取消不会再次投递；重启不会重复发送。
- 到点任务与 EventContext 分离；只有实际通知才创建新的 Reality ingress/turn。
- Dream active 时不创建或投递 Reality 消息，按任务类型得到明确 blocked/deferred 状态。
- 观测只返回任务状态、时间桶、计数和错误码，不返回敏感正文。

