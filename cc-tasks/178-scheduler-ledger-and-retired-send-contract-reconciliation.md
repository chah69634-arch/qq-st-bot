# Brief 178: Scheduler ledger uid 契约与退役主动发送路径对齐

## 背景

Scheduler 相关 14 个失败混合了两类问题：

1. `gating._decide()` 已按 owner 维度调用 `can_send(..., uid=uid)`，生日和花园测试替身仍使用旧签名；
2. `_pipeline_send()` 对 migrated trigger 已退役为 autonomy signal，旧测试仍期待直接返回 `"reply"`；
   `manual_trigger("period_reminder")` 也可能在旧 direct-send 分支与新 proposer/autonomy 语义间分叉。

这里不能简单让生产代码停止传 `uid`，否则会破坏多 owner/作用域隔离；也不能为了旧测试恢复 migrated trigger
直接发言。

## 施工范围

- 更新生日、花园 ledger 测试替身以显式接收并断言 `uid`，同时保留 birthday/time-sensitive lane 的豁免语义。
- 复核 `ProactiveLedger.can_send/record_send` 的 uid 作用域和 legacy 空 uid 兼容边界，补最小回归。
- 将 active-window 测试拆成：
  - 非 migrated compatibility trigger 验证 `_pipeline_send()` execution-only 行为；
  - migrated trigger 验证只产生 autonomy signal、返回 `None`、不直接调用 LLM/通道。
- 复核 `period_reminder` 的手动触发合同。缺少日期时必须返回稳定原因 `missing_period_date`，不得先排队再掩盖
  配置缺失；有日期时按当前 migrated/autonomy 合同验收，不恢复旧 direct send。
- 修正 autonomy effective-state 测试夹具，使其满足 runner admission 前置条件后再断言 schema；若生产 runner 在
  `talk_enabled=false` 时合理地无需调用 `chat_turn`，测试应改为断言 effective tools/events，而非索引空 spy。
- 更新 `docs/scheduler.md`、`docs/autonomy.md` 及控制面文档中 direct-send retired 的真值描述。

## 验收

- 相关测试：`test_birthday_ledger_exempt.py`、`test_garden_wake_bridge.py`、
  `test_r2b_active_window_gating.py`、`test_scheduler_active_window.py`、
  `test_scheduler_autonomy_effective_state.py`、`test_prompt_builder_period_scope.py`。
- 明确证明 DND、active-window、birthday exempt、time-sensitive garden lane 未被误伤。
- 不新增第二套 scheduler send 路径，不让 migrated trigger 绕过 autonomy admission/ledger。

