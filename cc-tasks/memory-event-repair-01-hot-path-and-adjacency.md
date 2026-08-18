# Brief 206 · MER-01 · 发送前热路径与顺序边算法

> 严重度：high / 第一张，必须先做
> 依赖：Brief 202 当前实现
> 参考：`core/memory/event_store.py`、`core/memory/fixation_pipeline.py`、`core/turn_sink.py`

## 现状问题

`append_event()` 每插入一条事件都会读取 scope 内全部历史事件，并重新尝试写全部 `previous/next/same_turn/reply_to` 边。普通轮 user/assistant 各 append 一次，这段同步 SQLite 工作又发生在 fanout 之前。账本增长后，单轮成本线性增长、累计成本接近 O(N²)，锁竞争还会叠加 busy timeout。

当前算法只新增邻接边、不撤销乱序插入后失效的旧邻接。例如先有 A、C，再补 B，会同时保留 A->C、A->B、B->C。

## 开工前影响审计

1. 画出 `record_assistant_turn -> post_process_critical -> capture_turn -> append_event -> fanout` 时序，记录当前同步边界。
2. 核对 event_store 进程锁、SQLite WAL/busy timeout、`uid_lock`、admin tombstone、迁移脚本和 proposer 的锁顺序。
3. 盘点所有直接调用 `append_event()` 的位置，区分实时写入、迁移、测试和后台维护。
4. 确认优化不改变旧 `event_log`、transport `msg_id`、turn_id 或发送失败语义。

## 改法

1. 把实时边生成改为只处理新事件所在 stream 和 turn：
   - 查询同 stream 的直接前驱与后继；
   - 必要时撤销被新事件切开的旧 `previous/next` 对；
   - 只处理当前 turn 的 `same_turn/reply_to`；
   - 只校验当前事件携带的 relation hints。
2. 不允许实时 append 再扫描全表或遍历全部历史 turn。
3. 为乱序、重复、同时间戳、迁移补写提供确定排序 `(occurred_at, seq, event_id)`。
4. 如果需要全量修复旧边，单独提供离线 reconcile/dry-run，不挂聊天路径；新增落盘状态则同步只读观测端点。
5. 记录 append 和 edge 阶段耗时、扫描/变更边数的内容无关指标，不能记录消息正文。
6. 评估是否仍需 5 秒 busy timeout；实时路径必须有明确的毫秒级预算和 fail-open 上限。

## 验收

- 账本从 10、1,000 到更大 fixture 时，单次 append 查询/写边数量保持常数级或对数级，不随全库线性遍历。
- A、C 后补 B，最终邻接只剩 A<->B<->C，不保留 A<->C 快捷边。
- 两次写同 event_id 不产生重复或误删邻接。
- user/assistant 同轮边保持幂等，跨 stream/uid/char/realm 不连边。
- event_store 错误或锁超时时，旧链路和可见发送仍可继续。
- 最小测试：event_store 边、dual-write、turn_sink 发送顺序和一个规模回归；使用 `pytest -n auto`。

## 不做什么

- 不改变 prompt、召回排序或角色工具结果 schema。
- 不在本工单回填 topic、模型候选边或历史迁移。
- 不把全量 reconcile 偷放进 slow queue 的逐轮任务。

