# CI-20260820 · GitHub Actions 失败修复批次

> 状态：open
> 来源：`cc-tasks/临时工单1.md`
> 基线：`main@7840d80`
> CI 结果：35 failed / 6054 passed / 66 skipped / 13 subtests passed
> 目标：按 7 个根因修复 35 个失败；每类完成 focused tests、差异检查并独立提交后，最后重跑总门禁。

## 一、结论

这不是 GitHub 上传、Actions runner 或依赖安装故障。CI 已正常收集并运行 6000 余项测试，失败来自当前提交中的代码/测试契约不一致。

35 个失败归并为 7 类：

| 顺序 | 工单 | 根因 | 直接/连锁失败 | 性质 |
|---|---|---|---:|---|
| 1 | CI-R1 | `storyline_weekly.py` 使用 Python 3.10 不接受的 f-string 表达式 | 15 | 生产代码语法阻断 |
| 2 | CI-R2 | External Companion 新增路径未登记，测试依赖未 checkout 的相邻仓 fixture | 9 | 数据分类遗漏 + CI 测试资产越界 |
| 3 | CI-R3 | Admin cachebuster 断言过期、页面有未 i18n 文本、三个新工具无双语 UI 描述 | 5 | 静态资源/i18n 配套遗漏 |
| 4 | CI-R4 | 三个 Memory Event 工具的 JSON schema 参数无 `description` | 1 | 工具注册契约遗漏 |
| 5 | CI-R5 | `event_channel` / `user_authored` 合理新增后，旧 spy 和精确断言未同步 | 3 | 测试替身/断言过期 |
| 6 | CI-R6 | dream isolation guard 扫描注释中的“余晖”产生误报 | 1 | 静态守卫误报 |
| 7 | CI-R7 | proposer 配置把测试的 `0.01s` 超时钳制为 `1s`，观测断言永远不触发 | 1 | 配置规范化与测试契约冲突 |

合计：35。

## 二、统一施工规则

每张子工单开工前读取 `AGENTS.md`、`docs/dev-environment.md` 及子工单列出的专题文档。涉及 runtime/scheduler/lifecycle 的工单还须读 `docs/runtime-lifecycle.md`、`docs/interaction-event-model.md`、`docs/security_model.md`。

每张工单必须：

1. 只修所属根因，不顺手改无关失败。
2. 使用 Python 3.10 兼容语法；本地 3.14 通过不能替代 CI 3.10 兼容检查。
3. focused tests 使用 `pytest -n auto`；语法工单另做 Python 3.10 CI 验证。
4. 检查三面闭环：后端控制/观测、desktop/mobile 消费面、原调用链及相邻回归。若确实无客户端影响，在提交说明中记录“不涉及协议/UI”，不要无故改客户端。
5. 执行 `git diff --check`，确认没有改动或恢复用户现有的 `cc-tasks` 删除项及 `临时工单1.md`。
6. 相关测试通过后立即独立 Git commit，再开始下一张。

## 三、CI-R1：先解除 Python 3.10 语法阻断

### 问题

`core/scheduler/triggers/storyline_weekly.py:471` 在 f-string `{...}` 表达式内部包含 `'\n'`。Python 3.10 报 `SyntaxError: f-string expression part cannot include a backslash`。该模块无法 import，导致 storyline 的 13 项测试以及 lineage/repair 各 1 项连锁失败。

### 修法

- 在 f-string 外先计算规范化 block 文本或 digest，再拼接 `eventlog:{digest}`。
- 保持 legacy material ID 的输入字节完全不变：`day + ':' + '\n'.join(block).strip()`，不得改变既有 receipt/cursor 幂等键。
- 增加一个明确锁定 legacy material ID 的回归断言，防止“修语法”时悄悄改变哈希。

### 必读与验证

- 必读：`docs/memory.md`、`docs/scheduler.md`、三份 runtime/lifecycle/security 文档。
- 测试：`tests/test_storyline_weekly.py`、`tests/test_memory_event_lineage.py`、`tests/test_memory_event_repairs.py`。
- CI 必须覆盖 Python 3.10；本地可先 `py_compile`，但不能只凭 Python 3.14 判定关闭。

### 验收

- 模块在 Python 3.10 可 import。
- 15 个失败全部消失。
- legacy receipt/cursor 的 ID 与修复前设计值一致。

## 四、CI-R2：External Companion 数据登记与自包含 fixture

### 问题

`core/data_paths.py` 新增了 5 个公开 accessor，但 `core/data_registry.REGISTRY` 未登记：

- `companion_root`
- `companion_receipt`
- `companion_receipts_root`
- `companion_session`
- `companion_stats`

同时 `tests/test_external_companion_runtime.py` 通过 `Path(__file__).parents[2]` 读取相邻仓 `PresenceKit-stardew-companion/protocol/...`。GitHub Actions 只 checkout 当前仓，因此 3 项测试报 `FileNotFoundError`。这是测试资产边界问题，不是 companion runtime 找不到生产文件。

### 修法

- 为 5 个 accessor 补 `PathMeta`。按现有实现，它们属于 runtime metadata-only、reality/shared 范围、全局或按调用方逻辑分区、Git ignore；具体 scope 值须与 `docs/data-taxonomy.md` 的既有枚举一致。
- fixture 必须变成当前仓可独立运行。优先把冻结协议的最小 JSON fixtures vendoring 到 `tests/fixtures/external_companion_v1/`，并在测试里从仓内读取。
- 同步建立协议漂移校验策略：当前仓模型校验 vendored fixture；跨仓兼容应由显式 multi-repo CI job checkout 固定路径/版本后运行，普通单仓 pytest 不得隐式依赖 sibling checkout。
- 不把真实 owner、token、路径或正文写入 fixture；只用虚构占位数据。
- 核对 `GET /observability/companion-events` 已覆盖新增 runtime 台账，本工单不重复新增端点。

### 必读与验证

- 必读：`docs/data-taxonomy.md`、`docs/external-companion-contract.md`、`docs/runtime-lifecycle.md`、`docs/interaction-event-model.md`、`docs/security.md`、`docs/security_model.md`、`docs/three-repo-interface-catalog.md`。
- 测试：`tests/test_data_registry.py`、`tests/test_external_companion_runtime.py`。
- 额外检查：从没有 sibling companion 仓的目录运行测试仍通过。

### 验收

- 5 个 accessor 均登记且分类通过 registry 守门。
- 单仓 checkout 可跑全部 companion runtime 测试。
- 若保留跨仓协议验证，它必须显式 checkout/version-pin，并与普通 pytest 分离。

## 五、CI-R3：Admin 静态资源、i18n 与新工具展示

### 问题

- Admin 实际 cachebuster 已升级到 `brief-216-memory-event-control-1`，但 `tests/test_admin_i18n_assets.py` 和 `tests/test_admin_owner_turn_api_ui.py` 仍硬编码 brief 199。
- `admin/static/pages/runtime-config.html` 的“全局启用”没有 `data-i18n`，导致 2 项中文可见文本守卫失败。
- `search_events`、`expand_event_window`、`get_related_events` 已注册为内置工具，但 Admin 工具页缺少中英双语说明。

### 修法

- 把 cachebuster 测试更新到当前唯一版本；更稳妥的是从 `index.html` 提取当前版本并验证 `core.js`/fragment 一致，避免每次升级留下多个旧 brief 常量。
- 为“全局启用”新增稳定 i18n key，并同时补 `zh-CN`、`en` 字典；HTML 用 `data-i18n`，保留中文 fallback。
- 为三个工具补 Admin UI 双语描述，不能修改工具 schema 的 canonical `description` 来绕过 UI 测试。
- 因修改 page fragment，按仓库规则再次升级 `ADMIN_UI_FRAGMENT_VERSION`，并同步 `index.html` 的 `core.js` query version；直接加载的 JS 若修改，也同步各自 `?v=`。

### 必读与验证

- 必读：`docs/tools.md`、`docs/feature-control-surface.md`、Admin static cache 规则。
- 测试：`tests/test_admin_i18n_assets.py`、`tests/test_admin_owner_turn_api_ui.py`、`tests/test_admin_tools_mcp_ux.py`、`tests/test_admin_static_split.py`。
- 浏览器检查：中英文切换后 runtime config 与工具说明均正确；若无法目检必须如实记录。

### 验收

- 5 个失败中属于本工单的 5 项全部关闭。
- 页面无未登记的静态中文。
- cachebuster 在 HTML、core fragment loader 和测试间一致。

## 六、CI-R4：Memory Event 工具 schema 描述完整性

### 问题

三个新工具的顶层说明、`examples`、`keywords` 已存在，但参数 schema 缺 `description`；CI 首先在 `search_events.query` 失败，修一个后还会继续暴露其余参数。

### 修法

- 为 `search_events`、`expand_event_window`、`get_related_events` 的每个 property 补简洁、准确的参数说明，包括 cursor、时间边界、limit、depth 等。
- array 参数同时检查外层 property 的说明；无需给 `items` 重复堆砌无意义文本，除非守门要求。
- 不改变类型、边界、required、危险级别、origin gate 或工具行为。

### 必读与验证

- 必读：`docs/tools.md`、`docs/memory.md`。
- 测试：`tests/test_tool_schema_descriptions.py`、`tests/test_memory_event_read_tools.py`、`tests/test_admin_tools_mcp_ux.py`。

### 验收

- 全 `_TOOL_REGISTRY` 参数描述守门通过。
- 三个工具导出的 function schema 行为字段无变化。

## 七、CI-R5：来源 provenance 新字段后的测试契约同步

### 问题

- 生产 `capture_turn()` 已增加 `event_channel`，但 `tests/test_pipeline_write_scope.py` 的两个 spy 不接受该关键字。TypeError 被 fail-open 捕获后表现为“没有调用”和 `IndexError`，不是生产路径漏调用。
- mobile owner turn 的 prompt capture 现在合理携带 `user_authored=True`，旧测试却要求字典精确等于 `{"origin": "mobile"}`。

### 修法

- 更新测试 spy，使签名覆盖当前 `capture_turn` 契约，并增加断言验证 `event_channel`、`event_source`、`char_id` 沿原路径正确透传；不要用任意 `**kwargs` 吞掉所有未来契约漂移。
- mobile 测试改为断言 `origin == "mobile"` 且 `user_authored is True`。不要删除生产字段迎合旧断言，该字段用于区分用户输入与 external companion stimulus。
- 检查 desktop/QQ/external companion 的相邻 provenance 测试，确保 phone input 为 true、opportunity 为 false，且 realm/source 不串线。

### 必读与验证

- 必读：`docs/memory.md`、`docs/channels.md`、`docs/interaction-event-model.md`、`docs/external-companion-contract.md`。
- 测试：`tests/test_pipeline_write_scope.py`、`tests/test_mobile_chat_channel.py`、`tests/test_external_companion_runtime.py`、相关 memory event dual-write 测试。

### 验收

- 3 个失败关闭。
- 测试明确验证新增 provenance，而非仅放宽断言。
- 不改变 mobile fanout、desktop stream 或记忆写入策略。

## 八、CI-R6：Dream isolation guard 消除注释误报

### 问题

`tests/test_dream_isolation_guard.py` 按敏感词扫描 reality 文件，命中了 `core/memory/source_policy.py` 中解释隔离政策的注释“梦境余晖”，并非现实代码调用 dream path。

### 修法

- 优先把守卫从任意文本子串扫描收紧到 AST/符号/路径引用，至少忽略注释和普通说明字符串，只阻止真实 import、属性调用或路径 accessor 使用。
- 若当前守卫结构不适合 AST，允许对该政策模块做精确到文件+标记的 allowlist，但必须写明为何安全；禁止全局放行“余晖”或整个 `core/memory`。
- 保留对真实 `dream_*` DataPaths、dream store/import 进入 reality loader 的拦截。

### 必读与验证

- 必读：`docs/memory.md` 的来源隔离、`docs/interaction-event-model.md`。
- 测试：`tests/test_dream_isolation_guard.py`，并新增一个临时 fixture/源码样例证明真实 dream path 引用仍会失败。

### 验收

- 政策注释不再误报。
- 注入一个真实 dream accessor/import 时守卫仍能检出。

## 九、CI-R7：Edge proposer 超时配置与观测测试

### 问题

测试设置 `scope_timeout_seconds=0.01` 以强制慢 scope 超时，但 `_config()` 将该值钳制到最小 1 秒；测试中的慢调用不足 1 秒，所以 `timed_out_scopes` 保持 0。当前失败不能直接证明生产 discovery loop 卡死，首先是配置规范化和测试假设不一致。

### 修法

- 明确生产配置最小值是否应保持 1 秒。默认建议保持生产下限，并让测试 patch timeout helper/常量或使用可注入 clock/timeout，避免真实等待 1 秒和时间抖动。
- 验证 `asyncio.wait_for` 超时后只释放当前 scope，继续扫描后续 scope，并记录 content-free `timed_out_scopes`；不得取消整个 discovery tick。
- 增加“超时 scope 后仍处理健康 scope”的断言，而不只检查计数。
- 不在 send 前路径增加等待；该 proposer 仍只由 scheduler 驱动。

### 必读与验证

- 必读：`docs/scheduler.md`、`docs/memory.md`、三份 runtime/lifecycle/security 文档。
- 测试：`tests/test_memory_event_edge_proposals.py`，必要时补 scheduler registration focused test。

### 验收

- 超时测试确定性通过，不依赖机器速度。
- 一个 scope 超时不会阻塞后续 scope。
- 观测计数准确，且不记录事件正文。

## 十、最终总门禁

7 张工单全部独立提交后执行：

1. 汇总运行上述所有 focused tests，使用 `pytest -n auto`。
2. 运行全量 `pytest -n auto`；目标是本批次 35 个失败归零，其他新失败须重新归因，不得混入旧结论。
3. 在 GitHub Actions 的 Python 3.10 与 3.12 矩阵验证，重点确认 CI-R1。
4. 运行 `git diff --check` 和 `git status --short`，不得提交 `.tmp`、fixture 外的运行数据、真实凭据或本机绝对路径。
5. 复核 Admin 静态 cachebuster、单仓 companion fixture、三端 provenance 和 scheduler 观测四条相邻链路。

批次关闭标准：35 个原失败全部通过，且每张工单有独立 commit、focused test 证据和三面闭环结论。
