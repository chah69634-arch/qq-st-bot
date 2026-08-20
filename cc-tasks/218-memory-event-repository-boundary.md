# Brief 218：Memory Event Repository 零数据改动边界

> 状态：proposed
>
> 性质：代码结构工单；不迁移、不转换、不扫描生产数据
>
> 架构依据：`docs/memory-storage-architecture-assessment.md`

## 一、目标

为当前 Memory Event Ledger 建立窄的 storage-independent repository port，并让现有 SQLite 实现作为默认 adapter 接入。

本工单只解决一个问题：上层调用方不再需要知道 Event Ledger 使用 SQLite。它不宣布新事实源，不改变双写策略，不处理 episodic/storyline JSON，也不为 PostgreSQL/Supabase 实现 adapter。

完成后应满足：

```text
pipeline / tools / admin / migration / shadow / lineage
                         |
                         v
                EventLedgerRepository
                         |
                         v
                SQLite implementation
                         |
                         v
          原 event_store.sqlite3（原路径、原 schema）
```

## 二、开工前必读

- `AGENTS.md`
- `ARCHITECTURE.md`
- `docs/memory.md`
- `docs/memory-storage-architecture-assessment.md`
- `docs/interaction-event-model.md`
- `docs/runtime-lifecycle.md`
- `docs/security_model.md`
- `docs/dev-environment.md`
- `docs/tools.md`

先只读核对当前调用方：

- `core/memory/event_store.py`
- `core/memory/event_query.py`
- `core/memory/event_shadow_recall.py`
- `core/memory/event_migration.py`
- `core/memory/lineage.py`
- `core/memory/fixation_pipeline.py`
- `core/tools/event_tools.py`
- `admin/routers/event_memory.py`
- `admin/routers/memory.py`
- `admin/routers/observability.py`
- `core/scheduler/triggers/event_edge_proposer.py`

## 三、数据冻结硬约束

本工单必须是零生产数据改动。

禁止：

- 运行 `scripts/migrate_memory_events.py` 或任何 memory migration/apply/rebuild 脚本；
- 枚举、打开、复制、校验或改写真实 `data/runtime/memory/**`；
- 连接云端服务器、下载云端 `data/` 或要求维护者提供生产数据库；
- 修改 `event_store.sqlite3` 的 schema、`PRAGMA user_version`、索引、表或列；
- 修改 JSON/YAML/Markdown 的路径、格式、默认值或兼容读取顺序；
- 创建生产 marker、migration state、trace 或新落盘物；
- 启动会加载生产 `config.yaml` / production sandbox 的 bot 进程做验证。

允许：

- 使用 pytest 的 `tmp_path`、项目 test sandbox 或内存 fake；
- 在临时目录创建全新的 SQLite fixture；
- 对测试 fixture 执行当前 schema initialization；
- 通过 monkeypatch / dependency override 验证 repository contract。

任何测试意外访问仓库真实 `data/runtime/memory`，本工单直接判定失败。

## 四、Repository contract

新增存储无关的窄端口，建议位置：

```text
core/memory/event_repository.py
```

名称可按现有代码调整，但 contract 必须覆盖当前已使用能力，且不得暴露：

- `sqlite3.Connection` / `sqlite3.Row`；
- SQL 字符串或 SQL predicate；
- filesystem `Path`；
- PRAGMA、table name、rowid；
- adapter 私有锁。

建议拆成以下只读/写入能力，避免一个万能 `get/set/query`：

```text
EventLedgerWriter
  append_event
  append_topics
  tombstone_event
  append_edge_proposal
  record_proposer_run

EventLedgerReader
  get_event
  search_events
  expand_event_window
  get_related_events
  recent_events_for_proposal
  proposal_budget_snapshot
  latest_proposer_run_at

EventLedgerHealth
  schema_status
  existing_ledger_health_code
  observability snapshots
```

可以使用一个组合 `Protocol`，也可以拆成三个小 Protocol。调用参数应继续使用 `MemoryScope` 和领域 query/options/result 类型。查询条件必须使用结构化字段；禁止把 `source_policy.sql_predicate()` 放进 port。

## 五、默认 adapter 与兼容 façade

当前 SQLite 行为必须原样保留。可采用下列演进方式：

1. 新增 repository Protocol 和默认 provider，例如 `get_event_repository()`；
2. 新增 SQLite adapter，初期允许委托现有 `event_store` / `event_query` 实现；
3. `event_store.py` / `event_query.py` 继续保留现有 public functions，作为兼容 façade；
4. 先选择少量上层 composition roots 改为注入 repository，不要求本工单机械改完全部调用方；
5. 后续工单再把 SQLite SQL/DDL 物理移动到 adapter，避免本单形成大规模搬文件。

这是允许的过渡结构：

```text
caller -> repository port -> current SQLite façade -> existing database
```

但禁止形成循环依赖。若 adapter 委托 façade，则 façade 不得反向调用默认 adapter。下一步物理拆分前，依赖方向必须在模块注释和测试中明确。

## 六、必须保持不变的行为

- `MemoryScope` 的 reality scope 校验；
- `event_id` 幂等和 duplicate result；
- tombstone 的可逆遗忘语义；
- deterministic edge 与 proposal table 分离；
- source isolation 默认过滤；
- `search/window/related` 的排序、cursor 和 truncation contract；
- query projection 的 text truncation、media projection 和 tombstone projection；
- SQLite busy/schema mismatch 的稳定错误码；
- role tools 的 ToolResult shape；
- admin endpoint、scope 和响应 shape；
- shadow recall 默认关闭且不进 prompt；
- proposer 默认关闭且只能写 candidate proposal；
- migration dry-run / backup gate / conflict classification；
- 当前 best-effort dual-write 和 fail-open send 行为。

特别说明：本工单不应顺手实现 turn 级事务。turn transaction 会改变失败与恢复语义，应由后续独立工单处理。

## 七、建议施工范围

新增：

- `core/memory/event_repository.py`：Protocol、结构化 query/options 和 provider；
- `core/memory/sqlite_event_repository.py`：当前 SQLite adapter，初期可薄委托；
- `tests/test_memory_event_repository_contract.py`：contract suite；
- 必要的测试 fake，例如仅放在 `tests/` 下。

按需最小修改：

- `core/memory/event_store.py` / `event_query.py`：只为适配稳定 public contract；
- 一个写入 composition root：建议 `_append_event_ledger()`；
- 一个读取 composition root：建议 `core/tools/event_tools.py` 或 shadow recall；
- 文档中的 ownership/边界说明。

本单不要求修改：

- episodic、mid-term、storyline、identity 的持久化；
- vector store；
- desktop/mobile 客户端；
- REST/WS schema；
- admin UI；
- feature control surface；
- production config。

没有新增设置、落盘状态、trace、队列、台账或外部接口，因此三面闭环结论应为 backend-internal、客户端无消费、无需新增 observability endpoint。现有 Event Ledger observability 必须继续通过原端点工作。

## 八、测试

新增 contract suite 必须能对默认 SQLite adapter 运行，并支持以后对其他 adapter 复用。至少覆盖：

1. append/get/search/window/related 的 contract；
2. duplicate event 幂等；
3. deterministic edges；
4. proposal 不进入 deterministic edges；
5. source isolation；
6. tombstone projection；
7. cursor validation 和稳定排序；
8. missing ledger 不因只读查询被创建；
9. invalid scope / schema mismatch / busy 的稳定错误；
10. fake repository 能替换默认 provider，且不会触发 SQLite 或 filesystem IO；
11. façade 与 repository 路径结果一致；
12. 测试期间未访问真实 `data/runtime/memory`。

相关回归至少运行：

```powershell
pytest -n auto tests/test_memory_event_repository_contract.py tests/test_memory_event_store.py tests/test_memory_event_read_tools.py tests/test_memory_event_query_observability.py tests/test_memory_event_shadow_recall.py tests/test_memory_event_migration_retention.py tests/test_memory_event_edge_proposals.py tests/test_memory_event_dual_write.py
```

如果部分实现只影响少量测试，先使用指定路径或 `pytest --testmon`；不得用不带 `-n` 的全量串行测试。临时目录按 `docs/dev-environment.md` 指向仓库内 `.tmp`，测试后只清理已验证位于仓库内的临时目录。

## 九、验收标准

- 有明确的 repository Protocol，签名中不出现 SQLite/SQL/Path 类型；
- 默认实现仍使用当前 SQLite 数据库路径和 schema；
- 至少一个写入 composition root 和一个读取 composition root 经 repository port；
- `event_store.py` / `event_query.py` 原 public API 兼容；
- 原有 tools/admin/shadow/migration/proposer 行为和结果 shape 不变；
- 没有新增或修改任何生产数据文件、schema、marker 或迁移状态；
- 没有访问云端服务器或真实生产 data；
- contract suite 与列出的相关回归通过；
- `git diff --check` 通过；
- 差异只包含本工单相关代码、测试和文档；
- 完成后立即创建一个独立 Git commit，再开始下一张工单。

## 十、非目标与后续解锁

本工单不做：

- SQLite -> PostgreSQL/Supabase；
- JSON/YAML -> SQLite；
- 生产数据迁移、备份、恢复演练或 schema upgrade；
- Event Ledger 唯一事实源切换；
- turn evidence 原子事务；
- 删除 legacy Markdown；
- 补齐 identity/relationship 的完整 lineage；
- 清理 episodic 私有 `_load/_save` 跨模块调用。

本工单完成后才解锁：

1. 派生 Memory 的窄 repository API；
2. Event Ledger SQLite SQL/DDL 从 façade 物理移动到 adapter；
3. turn 级 transaction/unit-of-work 设计；
4. 在生产数据到期、完成离线备份与恢复演练后，另开数据迁移工单；
5. 依据真实部署需求评估 PostgreSQL/Supabase adapter。
