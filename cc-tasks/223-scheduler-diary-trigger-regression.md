# 223：修复 23 点角色日记触发器被 proposer 异常阻断

**状态：** `open`
**范围：** 后端 scheduler / proposer / 角色内心日记维护链
**优先级：** P0（影响每日定时维护）

## 背景

服务器在 23 点调度轮次出现：

```text
AttributeError: AMBIENT
```

当前异常来自 `core/scheduler/triggers/practice.py::propose_practice_help()`：
它引用了 `UrgencyTier.AMBIENT`，但 `core/scheduler/urgency.py::UrgencyTier`
没有该成员。

当练习状态存在停滞超过 7 天的兴趣时，`practice_help` proposer 会实际构造
proposal，错误因此从潜伏状态变成运行时异常。

调度器每轮先执行 `run_shadow_tick()`，再执行包含
`_check_inner_diary_write()` 的维护任务集合。proposer 异常会越过 shadow tick
调用边界，直接进入 scheduler 外层异常处理，使本轮维护集合根本不会启动。
这就是角色每日 23 点日记未写入的直接原因。

相关历史：

- `71fa8e5` 引入 `practice_help` proposer，并把 practice 加入 proposer registry；
- 同一提交没有同步更新 urgency tier 合同；
- `5ed501a` 引入独立的 `inner_diary_write` 维护路径本身不是本次故障源；
- `daily_journal` 的 autonomy 迁移不应回滚，也不应重新承担日记文件写入副作用。

## 目标

1. 修复 `practice_help` 的 urgency 语义，使 23 点调度轮次不再抛出
   `AttributeError: AMBIENT`。
2. 任何单个可选 proposer 失败时，不能阻断其他 proposer 和维护任务。
3. 保持角色内心日记与用户可见主动消息的边界不变。
4. 增加能覆盖这次真实失败条件的回归测试和上线后可核验信号。

## 非目标与边界

本工单不做以下事情：

- 不新增 `UrgencyTier.AMBIENT` 作为本次错误的快捷修补。新增全局 tier 需要另行
  设计区间、竞争策略、文档和全量测试；
- 不把 `inner_diary_write` 加入 `MIGRATED_TRIGGERS`，不经过 autonomy talk gate、
  `ProactiveLedger`、channel 或用户可见消息路径；
- 不把 `daily_journal` 恢复为“主动发言成功后顺便写文件”；
- 不把 `practice` 后台练习 session 与 `practice_help` 用户提醒合并；
- 不在本工单内改写 practice 的模型路由、练习内容或客户端设置面；
- 不做历史日记文件迁移、重写或批量补写。

## 施工方案

### A. 修正 urgency 合同（P0）

将 `practice_help` 从不存在的 `UrgencyTier.AMBIENT` 改为现有且符合语义的
`UrgencyTier.FILLER`。

理由：该提醒是“停滞一段时间后的低频、非时间敏感提示”，不应压过生日、健康、
时间窗口事件或日常节奏触发器。不要使用 `REACTIVE`，也不要把它提升到
`DAILY_RHYTHM`。

若产品未来确实需要独立的 ambient 优先级，另开设计工单，完整修改：

- `UrgencyTier` 成员和 `URGENCY_RANGES`；
- proposer 竞争和 policy 文档；
- 管理面 effective state / 观测语义；
- 所有 urgency proposer 的参数化回归测试。

### B. proposer 级故障隔离（P0）

修改 `core/scheduler/gating.py::_collect_native_proposals()`：

- 每个 registry entry 独立执行；
- 单个 proposer 抛异常时记录 proposer 名称、异常类型和当前 tick；
- 跳过失败项，继续收集其他 proposal；
- 不对异常静默吞掉，也不以一个总异常终止整个 scheduler tick。

错误观测优先使用现有 scheduler 日志链，不新增不可查询的落盘台账。若实现选择
把失败项追加到 `gating_shadow.jsonl`，必须在同一变更中提供对应的只读观测端点，
并限制为 proposer 名称、异常类型、时间和计数，不写 prompt、日记正文、用户消息
或模型返回内容。

### C. 保持维护路径隔离（P0）

确认并锁定以下行为：

- `inner_diary_write` 仍由 scheduler 维护集合直接调用；
- 日记生成失败只影响对应角色/对应日期，不影响其他维护任务；
- 日记文件存在性仍是 logical day 幂等闸门；
- `daily_journal` 仍只表示用户可见主动消息的候选，不负责日记落盘。

如果在本次施工中触及 `_check_inner_diary_write()`，必须保持上述契约，并补充
跨午夜窗口测试，不能借机把它改成主动消息或 autonomy job。

### D. 后续架构审计（P1，设计结论必须记录）

单独审计 `practice_help` 当前通过 `execute_prompt()` 直接发言的路径。该路径是否
应迁移到 signal-first/autonomy，需要明确决策：

- 若迁移：只传递受限事实和稳定标识，不能把练习作品原文或任意 prompt metadata
  直接写入 signal；补 TTL、dedupe、talk gate 和 autonomy 观测；
- 若暂不迁移：将其明确标记为兼容路径，并保持默认关闭或可独立关闭；不能让它
  以未登记状态混在普通 proposer 中。

这项审计不应改变 `inner_diary_write` 的维护边界。

### E. 后续可靠性演进（P2，另开施工或在本工单只写设计）

当前角色日记生成包含两次 LLM 调用，长期可考虑改为带幂等键的后台维护 job：

```text
inner_diary_write:{char_id}:{logical_day}
```

由 worker 负责锁、重试、成功确认和失败退避，scheduler tick 只负责发现并入队。
该演进必须另行评估 slow queue 的持久化、观测端点、跨角色并发和备份策略，不能与
本次 `AMBIENT` 回归修复混为一个隐式大改。

## 必补测试

新增或补充以下覆盖：

1. `practice_help` 在停滞兴趣满足条件时返回合法 `FILLER` urgency；
2. `UrgencyTier` 所有调用点均引用已注册成员；
3. 构造一个抛异常 proposer，验证 `_collect_native_proposals()` 仍返回其他合法
   proposal，并记录错误；
4. 验证 proposer 异常不会阻断 `_check_inner_diary_write()`；
5. 23:00 生成当日文件，次日 01:00 使用同一 logical day 文件名；
6. 日记文件已存在时不重复调用 LLM；
7. `daily_journal` proposal 不产生日记写入副作用；
8. practice 关闭或 `help_proposer=false` 时，不再进入坏 proposer 分支。

建议 focused 验证命令：

```bash
pytest -n auto tests/test_inner_diary_write.py tests/test_gating.py tests/test_rhythm.py
pytest -n auto tests/test_scheduler_practice_proposer.py
```

测试必须使用隔离 sandbox，不读写生产 `data/`，不发起真实 LLM 或 channel 调用。

## 上线验收

### 代码验收

- `rg` 全仓不再存在 `UrgencyTier.AMBIENT`；
- proposer 单点异常不会越过 scheduler tick 边界；
- `inner_diary_write` 的 23:00–05:00 窗口和 logical day 幂等测试通过；
- 相关 focused tests 使用 `pytest -n auto` 通过；
- 差异检查确认未修改 `daily_journal` 的 autonomy 迁移契约。

### 服务器验收

上线后观察至少一个完整的 23:00–05:00 窗口：

- 不再出现 `AttributeError: AMBIENT`；
- scheduler 继续进入维护任务集合；
- 目标角色当天生成对应 `YYYY-MM-DD.md`，或在无真实 event log 时有明确的无写入
  日志原因；
- 同一 logical day 不重复生成；
- 如暂时关闭 `practice.help_proposer` 作为缓解措施，修复上线后再恢复并观察
  `practice_help` 是否符合单独的 autonomy 审计结论。

## 回滚与降级

- 代码回滚前可将 `practice.help_proposer` 设为 `false`，避免坏 proposer 进入
  proposal 构造；
- 不通过删除日记目录、删除 cooldown 文件或重置兴趣状态来“恢复”触发器；
- 若新 proposer 隔离逻辑出现副作用，优先关闭 `practice.help_proposer`，保持
  `inner_diary_write` 和其他维护任务继续运行。

## 提交要求

本工单完成后独立提交一个 commit，提交前完成 focused tests、`git diff --check`
和本工单范围审计。不得把无关的 `cc-tasks`、事件上下文或配置改动带入该提交。
