# EventContext 推送后 CI 失败：分类与修正工单

## 结论

本次 CI 共 `11 failed, 6103 passed, 66 skipped, 13 subtests passed`。失败集中在同一轮 EventContext / `char_id` 作用域改动，但并非同一个 bug：有 3 个生产契约遗漏、2 个测试/实现契约漂移，以及 1 个测试扫描器误报风险。

“每次仓库改进后 CI 都报错”主要不是 CI 随机不稳定，而是当前改动流程缺少跨边界契约闭环：新增字段先进入实现，再由全局测试在 push 后才发现 registry、UI、队列、mock 和返回对象没有同步升级。另有测试依赖源码正则和共享全局状态，使小改动更容易放大成多处失败。

## 工单列表

### P0-1：补齐 `event_context_trace` 数据路径注册

**现象**

- `test_no_unregistered_datapaths_methods`
- `test_registry_entry_fields_valid[event_context_trace]`
- `core/data_paths.py` 已新增 `DataPaths.event_context_trace()`，但 `core/data_registry.REGISTRY` 没有对应条目。

**修正**

在 `core/data_registry.py` 注册 `event_context_trace`，补齐 owner、分类、敏感级别、可清理/可观测等字段，并确认路径仍经 `core/sandbox.get_paths()` 获取。同步增加注册表单测，覆盖实际文件名和隔离目录。

**验收**

```text
pytest -n auto tests/test_data_registry.py tests/test_event_context_observability.py
```

### P0-2：处理 EventContext observer 设置接口的 UI 闭环

**现象**

`PUT /settings/event-context-observer` 未在 `admin/static/index.html` 被引用，也未加入 `NO_ADMIN_UI_WHITELIST`，导致 `test_write_routes_are_referenced_in_admin_ui_or_whitelisted` 失败。

**修正选择**

优先在管理面板加入读取/更新控件、effective state 和审计反馈；如果该接口确实只供运维/脚本使用，则加入带明确理由的白名单，并在 `docs/feature-control-surface.md` 记录“不提供 UI 的原因、权限 scope 和替代观测入口”。不能只为过测试添加无说明白名单。

**验收**

检查 GET/PUT、权限 scope、默认值、持久化和只读观测；运行：

```text
pytest -n auto tests/test_admin_ui_route_coverage.py tests/test_event_context_observability.py
```

### P0-3：修复 `capture_turn` 的 EventContext 向后兼容与错误暴露

**现象**

3 个 slow-queue 相关测试因 `capture_turn()` 新增 `event_context` 关键字而被旧测试替身拒绝：

- `test_handler_capture_turn_retry_passes_char_id`
- `test_legacy_payload_missing_char_id_warns_and_falls_back`
- `test_handler_capture_turn_retry_uses_scope_char_id`

随后 `post_process` 捕获 TypeError 并记录错误，导致：

- `test_post_process_passes_active_char_id_to_capture_turn`
- `test_post_process_uses_new_char_id_after_switch`

表现为 `capture_turn` 根本未成功调用。

**修正**

统一 `capture_turn` 调用契约：确认 `event_context` 是否必须字段；若非必须，调用方只在有值时传递，或为兼容旧替身/插件提供明确的适配层。同步更新所有 slow-queue handler、测试 spy 和外部调用点。不要用宽泛 `except TypeError` 静默吞掉参数契约错误；至少记录 handler、payload scope 和调用版本，并让测试失败原因可见。

**验收**

验证 scope 优先于旧 `char_id`，缺失时只走明确的 legacy fallback 并告警；切换角色后两轮分别写入对应 `char_id`：

```text
pytest -n auto tests/test_slow_queue_char_scope.py tests/test_slow_queue_scope_payload.py tests/test_pipeline_write_scope.py tests/test_event_context_propagation.py
```

### P1-1：修复 pipeline slow-queue 契约测试的误报并补齐 payload

**现象**

`test_pipeline_slow_queue_payloads_carry_char_id` 报 `enqueue('unknown')` 且 payload 只有 `s`。测试使用脆弱的正则和有限长度/括号扫描解析 Python 源码，遇到多行调用、字符串或嵌套表达式即可能截断；同时仍需确认真实 scoped handler 是否都携带 `char_id`。

**修正**

先用 AST 或直接测试 enqueue 捕获参数，删除基于字符位置的源码解析。再为每个需要作用域的 handler 建立统一 payload schema 校验，`consistency_check` 等非 scoped handler 明确列入类型定义，而不是隐式跳过。

**验收**

至少覆盖 `capture_turn_retry`、`summarize_to_midterm`、`user_profile_update` 的实际运行 payload，且测试不依赖源码排版。

### P1-2：稳定 scheduler pipeline registry 的返回对象契约

**现象**

`test_pipeline_send_reads_from_registry` 与 `test_hot_swap_registry_pipeline` 期望返回注册 pipeline 的回复，但 `_pipeline_send()` 在 fake `record_assistant_turn` 返回 `SimpleNamespace(fanout_failures={})` 时访问不存在的 `.context`，异常被统一错误处理吞掉后返回 `None`。

**修正**

明确 `record_assistant_turn` 返回类型（建议 dataclass/protocol），在 `_pipeline_send()` 只读取该类型声明的字段；测试 fake 必须使用同一最小协议对象。错误处理不得把契约错误伪装成正常 `None`，应保留异常类型和调用阶段。

**验收**

覆盖 registry 初始读取、热替换、fanout 失败和 context 缺失四种情况，确认异常路径有可观测日志。

### P1-3：修复测试隔离和 push 前门禁

**现象**

当前全量并行测试虽总体通过率高，但源码扫描测试、全局 registry、异步 slow queue 和共享 sandbox 容易在不同 worker/顺序下暴露不同失败。

**修正**

建立本地与 CI 一致的分层门禁：

1. 变更影响测试（`pytest --testmon` 或指定目录）；
2. 契约测试（registry/UI/scope/event context）；
3. 全量 `pytest -n auto`；
4. 对依赖全局 registry、环境变量、文件路径的测试使用 fixture 重置和唯一 sandbox。

新增字段时采用“先定义 schema/registry，再接入生产调用，再接 UI/观测，最后删兼容层”的顺序，并要求单独 commit 与验收记录。

## 共性根因

1. **跨模块契约没有单一来源**：`event_context`、`char_id` 同时存在于路径、队列 payload、writer、scheduler、UI 和测试替身中，新增字段没有 schema 或类型检查统一传播。
2. **失败被延迟到 push 才发现**：本地通常只跑局部测试，跨仓/管理面/全量契约检查在 CI 才执行。
3. **错误处理过度降级**：参数 TypeError 和返回对象 AttributeError 被捕获后变成 `None` 或日志，掩盖了真正的接口不兼容。
4. **测试实现过于脆弱**：源码正则扫描、手写 `SimpleNamespace`/spy、共享全局状态会把实现细节变化放大为假阳性或连锁失败。
5. **功能闭环不完整**：新增设置接口时只实现后端路由，未同时完成 UI、权限、观测和文档；新增落盘路径时未同步 registry。

## 根源改进建议

把“新增字段/路径/接口”升级为一张变更清单和一个 CI 检查器：schema、生产调用点、registry、UI/白名单、观测端点、权限、测试 fixture、文档必须逐项勾选；CI 在 PR 阶段运行 AST/schema 契约检查和受影响测试，而不是等 push 后才由全量失败列表反推遗漏。对关键返回值使用 dataclass/Protocol，对 payload 使用 TypedDict/Pydantic 校验，对错误处理禁止把契约异常转换为正常空值。这样能减少重复报错，但不能保证所有业务 bug 消失；业务逻辑仍需对应测试。

