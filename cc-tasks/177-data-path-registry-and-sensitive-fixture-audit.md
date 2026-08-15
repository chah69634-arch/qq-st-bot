# Brief 177: DataPaths 注册表闭环与敏感测试夹具清理

## 背景

全量测试中 `tests/test_data_registry.py` 有 5 个失败。`core/data_paths.py` 已新增以下公开方法，但
`core/data_registry.REGISTRY` 未登记：

- `memory_character_ids`
- `dream_group_transition_audit`
- `dreams_exit_lifecycle_path`
- `dreams_scenario_progress_audit_path`

另有 `tests/test_no_hardcoded_qq_number.py` 在 `tests/test_data_root_isolation.py` 命中真实 QQ 号字面量。
两者都是发布审计守卫失败，修复应保持机械、可审计，不改变运行时路径语义。

## 施工范围

- 为 4 个 DataPaths 方法补齐 `PathMeta`，逐项核对 durability、domain、scope 与 git policy。
- 不通过删除方法、私有化方法或放宽 `test_no_unregistered_datapaths_methods` 规避登记。
- 将测试夹具中的真实 QQ 号替换为明显虚构值；不得把真实号码加入白名单或扫描排除项。
- 检查本次涉及的路径是否已有对应只读观测端点；若某个新增 audit/ledger 尚不可观测，按 AGENTS.md
  补端点或在 `docs/known-issues.md` 和接口总账明确记录未闭环状态。

## 验收

- `tests/test_data_registry.py` 全部通过。
- `tests/test_no_hardcoded_qq_number.py` 通过，且扫描规则未放宽。
- `git diff --check` 通过；不修改真实 `data/`、`userdata/`。

## 独立提交边界

本 Brief 只提交注册表、必要观测/文档与敏感夹具替换，不夹带 Dream、Scheduler 或工具行为修复。

