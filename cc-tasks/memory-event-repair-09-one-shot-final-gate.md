# Brief 214 · MER-09 · Memory Event 一次性最终修复与关闭闸门

> 严重度：high
> 施工方式：**单张原子工单，一次完成，不再拆分**
> 依赖：Brief 195–213 当前实现
> 状态：completed（MER-09 原子提交，本提交）

## 一、目标

完成 Memory Event 第二轮审计发现的全部剩余问题，并给出可证明的最终关闭结论：

1. Reality 发送前 append 不再随 ledger / edge 数量线性退化。
2. 历史迁移不重复导入已双写事件，不丢失来源隔离，不猜测 trigger 时间或因果。
3. storyline 对素材、节点、cursor 和 inbox 实现可恢复的一致消费，不再静默丢输入。
4. shadow recall 只做一次同命名空间比较，turn/event coverage 真实可解释，seed 不再固定取最早命中。
5. proposer 只发现完整、版本匹配、只读验证通过的既有 ledger，扫描阶段绝不建库或迁移。
6. 来源过滤观测不再重复全表 COUNT 或把库存量伪装成本次拒绝量。
7. 旧修复工单、实现文档、观测 schema 和 Git 状态一次性收口。

本工单是最终关闭闸门。任一项未满足时，Memory Event repair 状态保持 open，不得以“主路径可用”代替验收。

---

## 二、开工前强制影响审计

改代码前先完成以下只读核对，并把结论写入本工单对应提交说明或测试注释；不得凭印象施工。

### 2.1 热路径与锁

画出并核对：

```text
record_assistant_turn
  -> pipeline.post_process_critical
  -> fixation_pipeline.capture_turn
  -> event_store.append_event (user + assistant)
  -> event_store.append_topics
  -> fanout / visible send
```

同时核对：

- `conversation_lock -> uid_lock -> event_store per-path RLock -> SQLite` 的实际顺序；
- admin query、tombstone、migration、proposer、shadow worker 是否存在反向取锁；
- `_initialize()` 当前执行的 DDL、PRAGMA、全表 UPDATE 和 commit；
- SQLite WAL、busy timeout、异常分类和 visible send 的 fail-open 语义；
- `append_event()` 的全部生产、迁移、后台和测试调用方。

### 2.2 迁移数据兼容

至少盘点以下 Markdown 形态：

- 已有 `{turn_id}:user` / `{turn_id}:assistant` ledger 行，同时 canonical event log 仍保留同一 turn；
- current 与 legacy 两处目录含同一天、同 turn 的重复块；
- `source:web`、`source:dream_echo`、`source:coplay`；
- 普通 user + assistant 块；
- assistant-only scheduler trigger，前面有普通 `## HH:MM` 块；
- assistant-only trigger 位于文件开头，没有可证明的消息时间；
- 旧日志没有 speaker、turn_id、source 或含矛盾 metadata；
- 已 tombstone、同 ID 不同正文、同 turn/actor 不同来源等冲突。

不得把“文件日期”“前一个块的时间”或 import time 描述成原始发生时间。

### 2.3 Storyline 消费边界

核对 `storyline.json`、`storyline_inbox.json`、episodic 输入和 event-log cursor 的所有 writer/readers，确认：

- 当前 cursor 仅为日期时，同日后续追加为何会永久跳过；
- `_apply_ops()` 哪些失败会被吞掉；
- `open_arc/append_node/set_status` 逐次落盘时，进程中断会留下哪些部分成功状态；
- cursor 前进、inbox 清空、node 写入是否能在重启后恢复或幂等重放；
- 新增 meta/state 字段对应的只读观测入口和敏感字段边界。

### 2.4 Shadow、source policy 与 proposer

核对：

- episodic `source_event_ids`、event-log `turn_id`、ledger event ID 的命名空间；
- `run_shadow_recall()` 与 pipeline 是否重复比较、何时丢弃 `new_event_turns`；
- `event_query.search()` 的 ASC cursor 与 shadow seed 目标；
- timeout 后线程、Python RLock、SQLite busy timeout 是否仍能占用 worker；
- source policy 在 search/get/window/related/lineage/migration/proposer 的覆盖范围；
- proposer 的 read-only health check 是否检查 schema version 和全部必需表。

---

## 三、必须实施的改动

### 3.1 从 append 热路径彻底移除 schema 维护和全表扫描

1. 拆分“建库/版本迁移”和“已健康 ledger 的实时 append”：
   - 新库创建或明确升级入口可以执行 `_SCHEMA_SQL`、`ALTER/UPDATE`；
   - 普通 `append_event()` 不得每次执行 `CREATE INDEX IF NOT EXISTS`、`PRAGMA table_info` 或迁移 UPDATE；
   - `UPDATE event_edges SET relation_type...`、`UPDATE ... schema_version...` 只能在版本迁移中执行一次。
2. 实时 append 只允许：
   - 一次事件 INSERT；
   - 当前 `(uid, char_id, realm, stream, source)` 的前驱/后继查询；
   - 当前 turn 查询；
   - 当前 event 的 relation hints；
   - 有界 topic 写入。
3. 旧 schema、未来 schema、损坏 schema 必须返回稳定错误并 fail-open 到旧记忆/发送链；不得在聊天轮次里自动修库。
4. 保留 250ms 或更严格的 SQLite 写预算，并新增明确的 `busy/locked/schema_mismatch` 内容无关计数；不能只暴露配置值。
5. 用 SQLite trace callback、query plan 或等价测试证明：ledger 从 10 增长到 10,000 条时，单次实时 append 的 SQL 数量和被访问的邻接范围保持常数级/索引级，不含全表迁移 UPDATE。

### 3.2 重做迁移的身份、来源和不确定性规则

1. per-message 解析 metadata，至少保留：
   - `speaker`；
   - `turn_id`；
   - `source`；
   - `trigger`；
   - metadata 所属消息边界。
2. 来源规则：
   - 原日志为 `web/dream_echo/coplay` 时，ledger 必须保留相同 source；
   - 普通旧日志才可使用 `legacy_migration`；
   - 未知或非法 source 不得被悄悄归为普通可召回证据，必须在 dry-run 中单列并采用保守策略；
   - 迁移后用 role tool、shadow 和默认 query 验证隔离来源仍不可见，admin 显式 source 仍可见。
3. 事件身份规则：
   - 有可信 turn_id + actor 时，优先对齐在线 canonical ID `{turn_id}:{actor}`；
   - 若 canonical ID 已存在，比较 scope、turn、actor、source 和安全内容指纹：一致计 `already_live/duplicate`，绝不再插一条 `legacy-*`；
   - ID 相同但证据不一致计 conflict，保留原 ledger，不覆盖、不 tombstone、不推进为成功；
   - 无可信 turn/actor 时才生成稳定 legacy ID。
4. assistant-only trigger 不得继承前一个普通 `## HH:MM` 块的时间。无法证明发生时间时，按 `legacy_unknown`/显式 unknown-time 契约处理，不制造精确时间或邻接因果。
5. dry-run 和 migration observability 至少增加内容无关计数：
   - `already_live`；
   - `source_isolated`；
   - `unknown_source`；
   - `assistant_trigger_unknown_time`；
   - `would_write`；
   - `duplicate`；
   - `conflict`；
   - current/legacy/override 分来源覆盖。
6. 修改 plan 语义后提升 migration state version。旧进度文件不得按新 entry 排序盲目续跑；需根据 source digest + state version 明确重置、拒绝或安全重算。
7. `--apply` 继续要求已验证离线备份和有界 batch；任何 conflict/写失败不得越过当前 offset。

### 3.3 Storyline 改为完整验证、幂等提交、精确 cursor

1. LLM ops 必须在任何写入前做完整批次验证：
   - op 类型只能是 allowlist；
   - 所有字段类型、title/arc 解析、status、ts/span、tags、material IDs 均合法；
   - 新开 arc 与后续 append 的引用能在同一计划内解析；
   - node limit、active arc limit、时间单调性预检查通过；
   - 任一 op 不可执行则整批拒绝，不写 arc/node/status，不动 cursor，不清 inbox。
2. 禁止继续使用“逐 op 写文件、异常后继续”的部分成功模式。先在内存副本上构造完整结果，再通过一个明确的 batch/commit API 原子写 storyline 主文件。
3. event-log cursor 改为版本化精确位置，至少包含 day + byte/block offset 或等价稳定 block ID，能够读取同一天上次位置之后的新内容。
4. 对旧日期字符串 cursor 制定一次性兼容策略：不得静默把同日剩余内容视为已消费。可采用稳定 block/material ID 重扫去重，或显式迁移 checkpoint；策略必须有测试和文档。
5. 为所有 episode、inbox 和 event-log block 分配稳定 material/input ID，并持久化有界 consumed IDs 或 batch receipt：
   - storyline 保存成功但 inbox 清理前崩溃，重启后不得重复建 node；
   - inbox 清理失败不得丢失未提交素材；
   - cursor、consumed receipt 与节点提交之间必须有可解释恢复规则。
6. 只有完整 batch 成功持久化后才能推进 `last_aggregated_at/cursor`；inbox 清理由幂等 receipt 驱动。
7. 新增或扩展只读 storyline aggregation 观测，至少返回 batch 状态、cursor 版本、待处理/已消费数量、最近失败码；不得返回原文、prompt 或事件 ID 全量。

### 3.4 Shadow comparison 只执行一次，并正确计算 omitted

1. pipeline 在旧召回结果准备好后，把结构化 legacy results 一次性交给 comparison；不得先用空结果比较再二次覆盖。
2. `new_event_turns` 在最终指标计算完成前不得删除。
3. 映射规则：
   - episodic 只用落盘 `source_event_ids`；
   - event-log turn_id 通过 scoped ledger 查询或 canonical IDs 映射该 turn 的实际事件集合；
   - 即使旧 turn 没有出现在新 recall，也必须计为 mapped-but-omitted，而不是 unmapped；
   - scope/source/time 不一致的结果拒绝参与比较并单独计数；
   - opaque episodic/vector ID 永不直接与 event ID 比较。
4. seed 选择必须真正符合记录的策略：
   - 若记录 `temporal_desc`，先从 SQL 取得最新匹配，再截 `seed_limit`；
   - 不得先 ASC LIMIT 最早 N 条后在内存倒序；
   - 如新增内部 order 参数，不改变 admin search 的既有 cursor 合同。
5. timeout 后后台 worker 必须在有界时间释放 shadow active slot。不能在不可取消的 Python RLock 或 5 秒 SQLite wait 上让后续所有 scope 长期返回 busy。
6. `old/new mapped/unmapped`、event overlap、turn overlap、coverage、extra、omitted 的分母和空集合语义写入文档，并与 admin observability 完全一致。

### 3.5 Proposer 使用严格、只读、全 schema 健康检查

1. discovery 只接受 resolver 指向的既有 canonical `.sqlite3` 文件。
2. read-only health check 必须验证：
   - `PRAGMA user_version == SCHEMA_VERSION`；
   - `events`、`event_edges`、`event_topics`、`event_edge_proposals`、`event_edge_proposer_runs` 全部存在；
   - proposer 查询依赖的关键列存在；
   - 文件可只读打开且 scope 匹配。
3. discovery 和 health check 不得调用 `_prepare_write_path()`、`_initialize()` 或任何 DDL/DML。
4. 已通过健康检查的 proposer write 使用“schema 已验证”写路径；如果调用期间 schema 状态变化，记录失败并退出，不能现场迁移。
5. 分别观测 missing、version_mismatch、table_missing、column_missing、database_error、timeout；不返回路径或 uid 原文。

### 3.6 修正来源过滤观测语义和查询成本

1. 删除默认 get/window/related/search 前对 scope 内全部 isolated rows 的重复 `COUNT(*)`。
2. 观测字段必须有真实语义，二选一并在文档中固定：
   - 精确统计本次候选中被 source policy 排除的数量；或
   - 只统计 `policy_filtered_query_count`，明确它是执行过滤策略的查询次数，不声称是拒绝事件数。
3. 若保留旧 `rejected` 字段，标记 deprecated 并给兼容期，不能继续累加库存量。
4. shadow 展开多个 seed 时，同一隔离事件不得因每次子查询重复计成多次“拒绝结果”。

### 3.7 文档、观测和 Git 收口

1. 同步：
   - `docs/memory.md`；
   - `docs/scheduler.md`；
   - `docs/tools.md`；
   - `docs/known-issues.md`；
   - `docs/three-repo-interface-catalog.md`；
   - 若设置/effective state 有变化，同步 `docs/feature-control-surface.md`。
2. 未接生产端点的 `triggered_by/derived_from/correction_of/media_of` 继续保持 `open/roadmap`，不得为了关闭工单伪造事件。
3. 不改变桌面/手机协议。确认管理面 read scopes、角色工具 owner/Path C 闸门和默认关闭开关未退化。
4. 将现有 `memory-event-repair-01..08`、repair README 与本工单纳入版本控制；更新 repair README 的实际状态和最终提交号，不留下 untracked 工单。
5. 本工单全部代码、测试、文档通过后只提交 **一个独立 Git commit**；未全部通过不得先提交半成品或把状态写成 completed。

---

## 四、最低回归测试

运行测试前必须先读 `docs/dev-environment.md`，使用仓库规定的并行入口和仓库内 TEMP/TMP。不得用全量串行 pytest。

至少新增/更新以下测试：

### 4.1 Event store 热路径

- 新库初始化与旧 schema 显式升级；
- 健康 ledger append 不执行 DDL/迁移 UPDATE；
- 10 / 1,000 / 10,000 events 下 SQL 数量不随规模增长；
- A、C 后补 B 只保留 A↔B↔C；
- duplicate append、同时间戳、不同 source/stream；
- locked/busy/schema mismatch fail-open，visible send 路径仍执行；
- topic 失败不回滚原始 event。

### 4.2 Migration

- current + legacy union 的同 turn/actor 只形成一个 canonical event；
- ledger 已有在线 event 时计 `already_live`，不新增 legacy duplicate；
- 同 ID 不同证据计 conflict，不覆盖；
- web/dream/coplay source 原样保留并继续被 role/shadow 隔离；
- assistant-only trigger 不继承前一普通块时间；
- state version/source digest 变化后的安全续跑；
- dry-run 零写入，apply 仍要求备份且 batch 可重入。

### 4.3 Storyline

- valid material + unknown arc、非法 op、node limit、未来/倒序 ts：整批零写入、cursor/inbox 不变；
- 同日第一次聚合后继续 append event log，第二次只读取新增部分；
- 主文件写成功/inbox 清理前模拟崩溃，重启不重复 node；
- 写失败后素材仍可重试；
- legacy date cursor 兼容迁移不静默漏同日内容；
- 每个 node 只包含自己选择 material 的 source IDs。

### 4.4 Shadow / proposer / source metrics

- 旧 event-log turn 命中新 event：turn overlap 正确；
- 旧 turn 在 ledger 存在但新 recall 未命中：计 mapped + omitted；
- opaque episodic ID 计 unmapped，不参与 Jaccard；
- 多于 seed_limit 的匹配返回最新 N 条，测试不得继续锁定最早 N 条；
- timeout worker 有界释放；
- proposer 对 version/table/column 不完整 ledger 全部跳过且零写入；
- source policy 观测不做重复全量 COUNT，指标与一次查询真实语义一致。

建议 focused 命令：

```bash
pytest -n auto tests/test_memory_event_store.py tests/test_memory_event_dual_write.py tests/test_memory_event_repairs.py
pytest -n auto tests/test_memory_event_migration_retention.py tests/test_memory_event_shadow_recall.py
pytest -n auto tests/test_memory_event_edge_proposals.py tests/test_storyline_weekly.py
pytest -n auto tests/test_event_read_tools.py tests/test_memory_event_query.py
```

测试文件名若与仓库实际不一致，应使用现有对应文件，不得为了照抄命令创建空壳测试。

---

## 五、最终验收闸门

以下条件必须全部满足：

- [ ] 聊天 append 的 SQL trace 中没有 DDL、schema PRAGMA 扫描或全表迁移 UPDATE。
- [ ] append 查询/边变更数量不随 ledger 规模线性增长。
- [ ] 迁移不会为已在线双写 turn 创建第二套 legacy 事件。
- [ ] 迁移后的 web/dream/coplay 仍被默认 query、role tools 和 shadow 排除。
- [ ] 无可信时间的 assistant-only trigger 未获得伪造精确时间或错误邻接。
- [ ] storyline 任一 op 不可执行时整批零写入，cursor/inbox 原样保留。
- [ ] storyline 能连续消费同一天后续追加内容，崩溃重启不重建 node、不丢素材。
- [ ] shadow event/turn mapped、unmapped、omitted 和 coverage 使用同命名空间且只计算一次。
- [ ] shadow `temporal_desc` 返回真正最新 seed，timeout 后 worker 有界释放。
- [ ] proposer 对不完整/错版本 ledger 零写入、零迁移。
- [ ] source observability 不再重复统计整个隔离库存。
- [ ] 管理面 scope、角色工具闸门、Reality/Dream/source 隔离和旧 event_log 路径均有最小回归。
- [ ] 文档、known issues、接口总账、观测 schema 与代码一致。
- [ ] `git diff --check` 通过；相关测试通过；工作树不遗留本系列 untracked 文件。
- [ ] 全部内容形成一个独立提交后，才将本工单状态改为 completed。

---

## 六、不做什么

- 不启用默认 shadow recall 或 proposer。
- 不把 shadow、proposal 或外部来源证据注入 prompt。
- 不改变 identity、episodic、event_log 的正式召回排序，shadow 内部 seed 修正除外。
- 不物理删除 ledger evidence，不修改 tombstone/owner retention 决策。
- 不新增跨仓桌面/手机协议或 UI。
- 不让模型候选自动升级为确定性 edge/topic/fact。
- 不为 `triggered_by/derived_from/correction_of/media_of` 伪造 stimulus/media event。
- 不顺手重构 Memory Event 之外的 scheduler、prompt 或工具系统。
