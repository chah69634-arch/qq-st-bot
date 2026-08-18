# Brief 215 · MER-10 · Memory Event Post-Gate 一次性纠偏

> 严重度：critical / high
> 施工方式：单张原子工单，一次完成；内部按阻断顺序施工，不拆成互相覆盖的临时补丁
> 依赖：MER-01 至 MER-09 当前实现
> 状态：open

## 一、背景与目标

MER-09 提交后的只读复核确认，最终关闭闸门仍有未满足项。最重要的问题不是新 ledger
查询本身，而是旧正式召回、历史迁移、storyline 兼容读取和灰度任务仍存在绕过或错误口径：

1. `event_log.search()` 未过滤 `source:web/dream_echo/coplay`，隔离来源仍可能经正式
   `6b_event_search` 层重新进入 Reality prompt。
2. migration plan 的 current/legacy 去重未比较 source，同 ID 不同来源可能被静默当作
   duplicate；dry-run 的 `already_live`/`would_write` 也没有检查现有 ledger。
3. storyline 用新旧路径 union 枚举日期，却只读取 canonical 文件；现有单 offset cursor
   也不足以正确消费两个物理来源。
4. shadow 为避免重复比较被改成旧召回完成后串行执行；线程超时后仍可能在 5 秒 SQLite
   busy timeout 中持有全局 active slot。
5. edge proposer 的输入窗口未应用 source policy，隔离来源正文可能进入 proposer LLM。
6. storyline 失败状态、过滤后空批次 checkpoint 和最终 Git 差异闸门没有真正闭环。

本工单完成后才能把 Memory Event repair 状态重新判定为 closed。在此之前：

- 禁止在服务器执行历史迁移 `--apply`；
- `event_shadow_recall` 与 `event_edge_proposer` 保持默认关闭；
- 不开始把新 ledger 自动注入正式 prompt；角色自由读取仍只走已有显式工具闸门。

---

## 二、开工前强制影响审计

改代码前先完成以下只读核对，并在提交说明中记录结论。不得凭局部测试直接施工。

### 2.1 来源隔离全链路

画出并核对：

```text
web / dream / coplay 回流
  -> capture_turn(source=...)
  -> event_log Markdown + Memory Event ledger
  -> event_log.search / episodic / storyline / salvage
  -> event tools / shadow / proposer
  -> prompt_builder 6b_event_search
```

逐一确认 source 标记在 user/assistant 块、旧无 speaker 块、current/legacy union、向量
`event_log` 索引和 recall trace 中的语义。集中 policy 必须同时覆盖旧 Markdown 正式召回和
新 ledger；不能只修 event tools。

### 2.2 服务器迁移与数据边界

盘点 current/legacy 同日文件、已在线双写的 canonical event、已有 migration state v2、
tombstone、非法 source 和同 ID 不同证据。明确哪些动作只读、哪些会新建 SQLite/state、
哪些会写 storyline meta。服务器已有自动备份不替代 `--apply` 前的显式快照验证。

### 2.3 Storyline 双路径消费

核对 `event_log._read_day_union()`、`list_days()`、storyline v1/v2 cursor、bounded receipts、
inbox cleanup 和 `uid_lock`。单个 `{day, offset}` 不能被直接套在两个物理文件上；必须先
决定 v3 cursor 是分别保存 canonical/legacy offset，还是以稳定 block receipt 作为权威。

### 2.4 并发和关键路径

核对 `fetch_context()` 中旧召回任务的开始/结束时序、shadow worker executor、Python
RLock、SQLite busy timeout、conversation/uid lock 和 visible send 边界。确认
`append_topics` 等现有发送前写入不会因本工单额外增加网络/LLM等待或无界数据库等待。

---

## 三、实现要求

### 3.1 堵住旧 `event_log.search()` 的正式来源泄漏

1. 建立可复用的 Markdown block source 判定，不让 `event_log.search`、salvage 和
   storyline 各维护一套不同正则。
2. `event_log.search()` 在关键词评分、trace 生成和 prompt 文本生成之前排除
   `web/dream_echo/coplay` 以及保守未知来源；普通无 source 历史块继续兼容。
3. user/assistant 同一 turn 只要属于隔离来源，整个逻辑块均不得进入结果；不得只删 meta
   行后保留正文。
4. 审计 `event_log` 向量索引：隔离正文不得通过共享 blob 相似度改变普通块召回排序。
   如现有索引无法按 block/source 区分，应在本工单内采用可解释的过滤/重建策略并记录
   兼容行为，不能宣称“输出没正文所以安全”。
5. `return_trace=True` 同样不得返回隔离块 snippet/turn_id；正式召回原有时间窗、普通块
   排序和卡片格式保持不变。

### 3.2 修正 migration 身份、冲突和真实 dry-run

1. current/legacy plan 去重必须比较至少：event ID、turn、actor、source、内容安全指纹、
   unknown-time/source 契约。相同 ID 但 source 不同必须计 conflict，不能 first-wins。
2. source 冲突不得把 `web/dream_echo/coplay/legacy_unknown` 降级成普通可召回来源，也不得
   覆盖现有 ledger。
3. dry-run 以只读方式查询既有 ledger，真实计算 `already_live`、`would_write`、
   `duplicate` 和 `conflict`；ledger 不存在时不得为了预览建库。
4. locked/schema mismatch/无法判定必须返回显式内容无关状态，不能把未知伪装成
   `would_write`。
5. 区分 plan 内重复/冲突、ledger 对比重复/冲突和重试次数，避免同一 conflict 每次重跑
   都被当成新的独立证据冲突。
6. plan/cursor 语义改变后提升 migration state version。旧 v2 state 必须因版本或 digest
   明确安全重算/拒绝，不得沿旧 offset 续跑。
7. apply 继续要求已验证离线备份、有界 batch、冲突处不推进 offset、旧 Markdown 不删除。

### 3.3 Storyline 使用真实 union 和可恢复 cursor

1. 不再采用“union 列日期、只开 canonical 文件”的组合。读取必须复用既有新旧 union
   语义，且同日两处独有 block 都可被消费一次。
2. cursor 升级为能表达两个物理来源的版本化结构，或改用稳定 block receipt；不得用
   canonical byte offset 解释 legacy 文件。
3. v1 日期字符串和 v2 `{day, offset}` 必须有明确兼容迁移：允许保守重扫，但已消费
   block 必须在进入 LLM 前按稳定 material ID 去除，不能只过滤 receipt 列表而仍把原文
   交给模型。
4. 只有 source-isolated/空白 block 的批次不调用 LLM，但应原子提交安全 scan checkpoint，
   避免每周重复读取；不得错误推进 episodic/inbox 的消费状态。
5. LLM、op validation、主文件写入和 inbox cleanup 失败时，cursor/inbox/node 保持既有
   原子语义，同时持久化内容无关 `last_failure_code`、阶段和时间。
6. `GET /memory/storyline/{user_id}` 至少提供 cursor version、双来源 checkpoint 摘要、
   inbox pending、bounded receipt 数、最近成功/失败状态；不得返回 prompt、正文或完整
   event ID 列表。

### 3.4 恢复 shadow 并行且保证有界释放

1. shadow 查询与旧召回并行开始；旧结果准备好后只执行一次 comparison。不得为了“一次
   比较”把完整 shadow 查询串行放到旧召回之后。
2. raw shadow result 与 comparison 分阶段：`new_event_turns` 保留到最终比较完成后再移除。
3. SQLite read timeout 必须小于 shadow 总预算并可观测，不能保留 5 秒 busy wait。
4. timeout 返回后，worker 必须在有界时间释放 active slot。不得用一个跨所有 uid/char 的
   全局锁让单个慢 scope 长期阻塞其他 scope；executor/slot 数也必须有硬上限。
5. shadow 继续默认关闭、不进 prompt、不写派生记忆；超时、busy、cancelled 分开计数。

### 3.5 Proposer 应用来源边界

1. `recent_events_for_proposal()` 默认排除所有 isolated source，且查询发生在正文投影前。
2. proposer LLM 不得看到隔离正文，也不得建立普通事件与隔离事件之间的候选关系。
3. proposal endpoint 写入再次验证 scope/source policy，不能只依赖输入窗口过滤。
4. 增加内容无关 filtered/input 计数；默认开关、预算、只读 discovery 和 schema health
   行为保持不变。

### 3.6 清理最终闸门和文档

1. 修正 MER-01 至 MER-08 文件 EOF 空白，使本系列 `git diff --check` 真正通过。
2. 更新 `docs/memory.md`、`docs/known-issues.md`、`docs/three-repo-interface-catalog.md` 中
   source、storyline cursor、shadow timeout 和 migration dry-run 的真实合同。
3. MER-09 不得继续写成无条件 closed；在本工单验收前标明 post-gate reopened。MER-10
   全部验收后再同时关闭，不保留互相矛盾的状态描述。
4. 不修改或生成 `data/`、`userdata/`、本地备份、SQLite、migration state 等运行数据。

---

## 四、最小回归矩阵

按 `docs/dev-environment.md` 使用 `pytest -n auto`，优先跑相关文件，不跑串行全量。

### 4.1 正式召回与 source

- 同日普通块 + web/dream/coplay 块：`event_log.search()` 及 trace 只返回普通块；
- 隔离块关键词完全命中时，`prompt_builder` 仍不出现其正文；
- 旧无 source/speaker 块保持可召回；时间窗和 current/legacy union 不回归；
- event-log 语义相似度不被隔离正文抬高。

### 4.2 Migration

- current 普通、legacy web 的同 canonical ID 计 conflict，反向顺序结果一致；
- 同 source/turn/actor/正文计 duplicate；已有在线 event 计 already_live；
- dry-run 的 would_write 等于真实可写数，且不创建 ledger/state；
- locked/schema mismatch 显式失败；state version 变化不沿旧 offset 续跑；
- apply 冲突不覆盖、不推进，重试不虚增独立冲突数。

### 4.3 Storyline

- legacy-only 日期、canonical-only 日期、同日双路径独有块均只消费一次；
- v1/v2 cursor 升级后同日后续 append 不漏，重扫 receipt 不把旧正文再次交给 LLM；
- 仅隔离块时不调用 LLM但 checkpoint 前进；
- invalid output/write failure 记录失败码且不动业务 cursor/inbox/node；
- commit 后 cleanup 前崩溃，重启不重复 node。

### 4.4 Shadow / proposer /关键路径

- 人为阻塞旧召回时可证明 shadow 已并行启动，最终 comparison 只调用一次；
- SQLite locked 超过预算后，active slot 在硬上限内释放，另一个 scope 不长期 busy；
- proposer 输入和 proposal 写入双重排除 isolated source；
- shadow/proposer 默认关闭，普通对话路径无新增 LLM/网络往返；
- Memory Event 角色工具、admin forensic 显式 source、Dream/Stage realm 隔离继续通过。

建议 focused 命令：

```bash
pytest -n auto tests/test_event_log_source_tag.py tests/test_event_log_union.py tests/test_event_log_search_cards.py
pytest -n auto tests/test_pipeline_event_log_source.py tests/test_pipeline_memory_scope_integration.py
pytest -n auto tests/test_memory_event_migration_retention.py tests/test_storyline_weekly.py
pytest -n auto tests/test_memory_event_shadow_recall.py tests/test_memory_event_edge_proposals.py
pytest -n auto tests/test_memory_event_repairs.py tests/test_memory_event_read_tools.py
```

若仓库没有某个建议文件，选择实际覆盖同一调用链的现有测试，不创建空壳测试。

---

## 五、服务器部署与数据验收

1. 本工单代码提交不得携带运行数据；部署前记录代码版本并确认自动备份/快照可恢复。
2. 部署代码后先保持 shadow/proposer 关闭，只运行只读 migration dry-run 和 storyline
   observability；对账 source/conflict/already_live/would_write。
3. dry-run 与服务器样本对账通过后，另行由维护者决定是否执行带显式快照验证的
   `--apply`。代码合入不自动授权迁移。
4. cursor schema 只允许通过兼容读取和原子 checkpoint 懒升级；不批量重写或删除旧日志。
5. 发现 source 冲突、schema mismatch 或无法解释的 would_write 时停止 apply，保留原文件
   和 ledger，依靠快照/旧读取链回退。

---

## 六、最终验收闸门

- [ ] 正式 `event_log.search`、trace 和 prompt 不再出现 isolated source 正文。
- [ ] migration 同 ID 不同 source 稳定计 conflict，dry-run 数字来自现有 ledger 只读对比。
- [ ] dry-run 零写入，apply 仍需已验证备份且冲突不推进。
- [ ] storyline 真正消费 current/legacy union，旧 cursor 和同日 append 均不漏不重。
- [ ] storyline 空过滤批次和失败状态均可观测，cursor/inbox/node 原子语义不回归。
- [ ] shadow 与旧召回并行、只比较一次，timeout worker/slot 有界释放。
- [ ] proposer 的读取和写入两端均拒绝 isolated source。
- [ ] shadow/proposer 默认关闭，角色工具/admin/Dream/Stage 边界保持原合同。
- [ ] 相关 focused tests 使用 `pytest -n auto` 通过。
- [ ] `git diff --check` 通过，工作树无本系列 untracked/运行数据文件。
- [ ] 文档、known issues、接口总账、管理面观测与代码一致。
- [ ] 单独 Git commit 完成后，MER-09/MER-10 状态才可同时改为 completed。

---

## 七、不做什么

- 不在本工单执行服务器 migration apply 或批量数据修复。
- 不删除、覆盖或重写旧 event-log、ledger evidence、tombstone、storyline node。
- 不把 shadow/proposal/event evidence 自动注入正式 prompt。
- 不让模型决定 source、event ID、迁移冲突或 cursor。
- 不更改 identity/episodic 的正式召回排序，不扩展客户端协议或设置面。
- 不以默认关闭为理由跳过 source、线程释放或观测测试。
