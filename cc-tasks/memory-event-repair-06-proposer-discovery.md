# Brief 211 · MER-06 · 候选边调度器发现与运行边界

> 严重度：medium / 第六张
> 依赖：MER-01、MER-04、MER-05
> 参考：`core/scheduler/triggers/event_edge_proposer.py`、`core/data_paths.py`、`core/scheduler/loop.py`

## 现状问题

调度器枚举用户目录时检查 `event_store.sqlite`，但标准路径是 `event_store.sqlite3`，所以即使开关开启也会跳过全部账本。现有测试直接调用 `_propose_scope()`，没有覆盖真实 scheduler discovery。

## 开工前影响审计

1. 核对 scheduler 注册、cooldown、`uid_lock`、模型超时和每日预算的完整路径。
2. 确认 ledger 路径只能通过 `path_resolver/get_paths()` 判断，不能再复制文件名。
3. 检查多角色、多 uid、空目录、损坏 schema、迁移中的数据库和 tombstone-only 窗口。
4. 确认 feature flag 默认关闭，修复后不会意外立即产生历史积压调用。

## 改法

1. 用 `get_paths().event_store(uid, char_id=...)` 或 resolver 获取规范路径，删除字面文件名判断。
2. discovery 只处理已存在且 schema healthy 的 Reality ledger；损坏或升级中状态记录内容无关失败，不初始化新库。
3. 给 scheduler 外层增加明确模型调用 timeout；单个 scope 失败不能阻塞其他维护任务。
4. 开关从 false 切 true 时仍受 cooldown、每日调用和 token 预算约束，不追赶全量历史窗口。
5. 增加 discovery 计数：扫描 scope、eligible、skipped reason、run/failure；已有观测端点同步展示。

## 验收

- 真实标准路径能被 scheduler 找到，错误扩展名不会再出现。
- 多角色/多 uid 只处理各自 healthy ledger，不创建缺失数据库。
- disabled 时零模型调用；enabled 时预算和 cooldown 生效。
- 模型超时、坏 JSON、坏库只影响当前 scope。
- 候选仍只写 proposal 表，不进入确定性边、prompt 或记忆固化。
- 最小测试必须从 `_check_event_edge_proposer()` 入口覆盖 discovery，不得只测 `_propose_scope()`；使用 `pytest -n auto`。

## 不做什么

- 不自动接受候选边。
- 不修改确定性边或事实状态。
- 不在逐轮 slow queue 调用模型。

