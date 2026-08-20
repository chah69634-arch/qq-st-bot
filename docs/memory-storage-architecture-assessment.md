# Memory / Event Ledger / Storage 架构判断

> 状态：current-state assessment
>
> 范围：当前仓库的 Memory、Memory Event Ledger、派生记忆、召回、关系、迁移、溯源与持久化链路。
>
> 本文是架构判断，不是迁移方案，也不授权读取、复制或改写生产环境数据。

## 一、结论

本仓库应归类为：

**B. 架构方向合理，但应该现在抽象 Storage/Repository 层，以便未来从当前实现切换到其他 SQLite 布局或 PostgreSQL。**

这个结论不等于“应该迁移到 Supabase”。当前实现并不是用 JSON 手搓一个简陋版 Supabase：

- Memory Event 证据账本已经使用 scoped SQLite；
- 语义向量索引已经使用 SQLite + sqlite-vec；
- JSON/YAML 主要承载有限状态桶、派生记忆文档和用户可读状态；
- JSONL/Markdown 主要承载审计、trace、旧事件流水与历史迁移来源。

真正需要处理的是边界问题：Event Ledger 已经数据库化，但 repository 端口尚未显式形成；旧 Memory pipeline 的部分模块仍通过私有 load/save 函数和整文件 read-modify-write 相互耦合；新旧事件链仍是 best-effort 双写，尚未宣布 SQLite Ledger 为唯一事实源。

因此，当前应先做不改数据的代码边界整理，再根据真实运行规模、并发和部署需求决定是否迁移存储。数据库品牌不是当前的首要架构决策。

## 二、当前实际存储

现实侧用户记忆的主根目录由 `core/data_paths.py` 和
`core/memory/path_resolver.py` 统一解析为：

```text
data/runtime/memory/{char_id}/{uid}/
```

主要持久化物如下：

| 领域对象 | 当前格式 | 主要 owner |
|---|---|---|
| 原始 Memory Event 证据 | `event_store.sqlite3` | `core/memory/event_store.py` |
| Event 查询 | SQLite 只读查询 | `core/memory/event_query.py` |
| 向量派生索引 | `vector_store.db`，SQLite + sqlite-vec | `core/memory/vector_store.py` |
| short-term | `history.json` | `core/memory/short_term.py` |
| legacy event log | 每日 Markdown + `full_log.md` | `core/memory/event_log.py` |
| mid-term | `mid_term.json` | `core/memory/mid_term.py` |
| episodic | `episodic.json` + `memory_index.json` | `core/memory/episodic_memory.py` |
| identity | `identity.yaml` | `core/memory/user_identity.py` |
| storyline | `storyline.json` + inbox JSON + archive Markdown | `core/memory/storyline.py` |
| relationship facts | `relationship_facts.yaml` | `core/relationship_facts.py` |
| provenance / recall / query trace | JSONL | 对应 trace/accessor 模块 |
| profile / hidden state / mood / action 等 | 独立 JSON/YAML | 各领域模块 |

仓库中没有 PostgreSQL、Supabase、SQLAlchemy、Redis 或其他远程数据库实现。

Event Ledger SQLite 已具有：schema version、WAL、busy timeout、主键、唯一约束、查询索引、事务提交、幂等插入、tombstone、确定性 edge、模型 proposal 表和 health check。向量库也是 SQLite，但被定义为可重建的派生索引，不是事实源。

## 三、当前代码分层

按实际调用链，系统可分为：

```text
输入 / trigger / channel
          |
          v
fixation_pipeline.capture_turn()
          |
          +-- short_term history.json
          +-- legacy event_log Markdown
          +-- Memory Event SQLite Ledger
          |
          v
       slow queue
          |
          v
      mid_term.json
          |
          v
 episodic.json + memory_index.json
          |
          +-- identity.yaml
          +-- storyline.json / storyline_inbox.json

召回：
short_term + event_log search + episodic ranking
    + vector_store.db + Event Ledger shadow recall
          |
          v
      prompt builder

角色侧事件工具：
search_events / expand_event_window / get_related_events
          |
          v
      event_query.py
          |
          v
   event_store.sqlite3
```

领域层已经具备的边界：

- `MemoryScope` 明确定义 global / reality / dream；
- artifact resolver 集中管理路径，业务代码不应任意拼接 `data/`；
- 工具层只调用 Event Query API，不直接执行 SQL；
- pipeline 通过 Event Store API 写证据；
- lineage、migration、shadow recall 通过 Event Store/Query 模块访问账本；
- deterministic relation 与 model candidate relation 在语义和表结构上分开。

尚未完成的解耦：

- `event_store.py` 同时承担领域校验、SQLite adapter、DDL、schema upgrade、edge 生成、proposal persistence 和 observability；
- `event_query.py` 直接依赖 `sqlite3.Row`、PRAGMA、SQLite SQL 和 `event_store` 私有锁；
- `source_policy.sql_predicate()` 返回 SQL 片段，而不是存储无关的查询条件；
- fixation 和 lineage 会调用 `episodic_memory._load_memories()`、`_save_memories()`、`_rebuild_index()`；
- episodic、mid-term、storyline 等模块将领域规则、整文件读改写和恢复策略放在同一模块；
- relationship suggester 仍直接扫描 legacy Markdown，而非查询统一的证据仓库。

所以当前是“模块边界部分清晰、持久化端口尚未稳定”，不是完全混在一起，也不是已经可以无成本换库。

## 四、哪些是 Memory 领域能力，哪些是数据库能力

无论使用 JSON、SQLite 还是 PostgreSQL，都必须由 Memory/Event Architecture 保留：

- 事件、turn、来源、realm、channel 和 actor 的身份语义；
- 原始证据与 episodic / storyline / identity 等派生记忆分层；
- source/realm 隔离和 Reality/Dream/Stage/web/coplay 的准入策略；
- deterministic relation 与 model candidate relation 分离；
- candidate 的验证、审核状态和置信度语义；
- derived memory 指回原始事件的 lineage；
- episodic 的 strength、decay、retrieval boost 和固化条件；
- identity 与 storyline 的内容边界；
- forgetting/tombstone 的产品语义；
- shadow recall comparison 和灰度切换；
- legacy Markdown 如何被解释成事件。

可以交给 SQLite/PostgreSQL 更可靠处理的能力：

- 唯一约束和外键/endpoint 一致性；
- 多行、多表原子事务；
- 并发写和 compare-and-set；
- indexed filtering、ordering 和 cursor pagination；
- schema migration/version；
- 增量更新、恢复和一致性约束；
- repository 内部的数据查询与统计。

当前文件存储自行承担了临时文件 replace、`.bak`、整文档 read-modify-write、进程内 uid lock、数组唯一性检查、排序、容量裁剪、JSONL rotation 和多文件幂等标记。这些是未来可以逐步下沉到数据库的部分，但不是立即重构全部 Memory 的充分理由。

## 五、Event Ledger 专项判断

Event Ledger 的概念设计应保留：

1. 原始消息是事实证据，派生记忆不是证据替代品。
2. `event_id` / `turn_id` / `source` / `realm` / `channel` 等身份必须明确。
3. episodic/storyline 通过已存 ID 指回证据，不按摘要文本猜 lineage。
4. 确定性 edge 与模型 proposal 分开，模型不能直接写确定性关系。
5. 隔离来源默认不能通过角色工具或 shadow recall 回流 Reality prompt。
6. 新 recall 先 shadow comparison，不直接替换旧召回。
7. legacy migration 默认 dry-run、需要已验证备份、支持可重入小批次。
8. tombstone 保留稳定身份和 lineage，可清除 recallable payload。
9. 查询工具必须 bounded、scoped、可分页、可观测。

当前仍有四个重要限制：

- Ledger 写入是 additive/best-effort；失败不会阻止 legacy memory，因此尚不是唯一事实源；
- 同一 turn 的 user event、assistant event、topics 与 legacy writers 不共享一个事务；
- Event Store 目前只接受 reality scope，Dream/Stage 等还不是统一多-realm ledger；
- lineage 正式覆盖 episodic 和 storyline node，但 identity 与 relationship facts 尚未形成完整的结构化 event lineage。

这些限制需要分别处理，不能用“改成 PostgreSQL”代替设计决策。

## 六、迁移影响评估

### Event Ledger：SQLite 换 PostgreSQL/Supabase

在 repository contract 稳定后，通常无需改变：

- `MemoryScope`；
- EventRecord 的领域字段；
- pipeline 生成事件的规则；
- source/realm policy 的语义；
- relation type 和 proposal policy；
- shadow comparison；
- tool/admin 对外结果 contract；
- migration 的解析和冲突判定规则。

需要抽象或重写：

- connection、transaction 和 schema migration adapter；
- SQLite PRAGMA/WAL/user_version；
- SQLite SQL、`INSERT OR IGNORE`、URI read-only 连接和 row projection；
- per-file discovery、backup/recovery；
- SQLite-specific indexes 和 health checks。

### 全部派生 Memory：JSON/YAML 换 SQL

这会继续影响 episodic、mid-term、storyline、identity、profile、relationship facts、short-term，以及 fixation/lineage 对私有文件函数的调用。它属于中型到大型迁移，不应与 Event Ledger repository 抽取绑成一次施工。

## 七、建议的演进顺序

### 第一步：只抽 Event Ledger repository 边界

- 建立存储无关的 Event Ledger port；
- 当前 SQLite 实现仍是唯一默认 adapter；
- `event_store.py` / `event_query.py` 保留兼容 façade；
- 不改路径、schema、文件格式、查询结果或运行时开关；
- 不读取、不迁移、不回写生产数据；
- 只使用测试 sandbox 和临时数据库验证 contract。

施工定义见 `cc-tasks/218-memory-event-repository-boundary.md`。

### 第二步：清理派生层的私有 IO 耦合

为 episodic/storyline 建立窄 public repository API，先消除跨模块 `_load/_save` 调用。仍可继续使用 JSON，实现与数据格式均不必同时改变。

### 第三步：明确事实源与 turn 级事务

在 soak、迁移和一致性证据满足后，单独决定 Event Ledger 是否成为 canonical evidence source，并设计 turn evidence 的事务边界。该步骤会改变失败/恢复语义，不能混入第一步。

### 第四步：按真实需求选择数据库

只有出现多进程写、多设备云同步、远程协作、跨用户查询、托管备份或 SQLite 已经测得的容量/锁瓶颈时，再评估 PostgreSQL/Supabase。单用户、本地优先、隐私敏感的部署继续使用 SQLite 是合理选择。

## 八、维护者决策

如果由本文作者维护当前项目：

- 现在不会迁移到 Supabase；
- 会继续使用本地 SQLite 作为 Event Ledger 和向量索引；
- 会立即建立窄 repository contract，但不做生产数据迁移；
- 会先补齐事务、lineage 和事实源准入，再决定派生 JSON 是否需要迁入 SQLite；
- 会把 PostgreSQL/Supabase 视为部署与同步需求的候选实现，而不是 Memory Architecture 的替代品。

最终判断：Storage、Memory Architecture、Event Ledger 三层没有完全混在一起，但边界尚未收口。方向没有选错；当前最有价值的改动是稳定 repository 边界，而不是更换数据库品牌。
