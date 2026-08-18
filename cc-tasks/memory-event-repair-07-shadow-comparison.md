# Brief 212 · MER-07 · Shadow Recall 新旧对比口径

> 严重度：medium / 第七张
> 依赖：MER-03、MER-04、MER-05、MER-06
> 参考：`core/memory/event_shadow_recall.py`、`core/pipeline.py`、`core/recall_trace.py`

## 现状问题

当前 overlap 直接比较新侧 event IDs 与旧侧 episodic IDs、vector source IDs。episodic ID 与逐消息 event ID 不在同一命名空间；event_log vector 的 turn_id 也不等于 `turn_id:user/assistant`。因此 overlap 通常接近零，不能判断新旧召回是否命中同一证据。

## 开工前影响审计

1. 列出旧召回各层 ID 的语义：episodic ID、event_log turn_id、vector source_id、fallback ID。
2. 盘点哪些旧结果已有 `source_event_ids`，哪些只能映射到 turn，哪些完全 unknown。
3. 确认 source policy、时间范围和查询文本归一化在新旧路径一致。
4. 检查 shadow await 时序、线程取消、120ms 预算和 recall_trace 敏感字段。

## 改法

1. 定义统一 comparison key：优先使用落盘 `source_event_ids`；event_log turn_id 可确定映射为该 turn 的事件集合；无法映射的结果计入 `unmapped_old_count`，不能假装不重叠。
2. 分别报告：
   - event-level overlap；
   - turn-level overlap；
   - old/new mapped 与 unmapped 数量；
   - coverage、额外事件数和遗漏事件数。
3. 新侧 seed 不应固定取最早的 LIKE 命中；排序策略必须与评估目标一致，并显式记录 temporal/relevance 口径。
4. timeout 后后台线程若仍运行，不能继续占用关键锁或无限累计；使用可取消/短查询设计。
5. 保持 shadow 不进入 prompt、不写派生记忆，默认关闭。

## 验收

- 同一 turn 的旧 turn_id 与新 `:user/:assistant` 能正确计为重叠。
- episodic 通过 `source_event_ids` 映射；无法映射的旧条目单独统计。
- 不再直接对不同 namespace 做 Jaccard。
- source、时间窗和 scope 不一致的结果不会参与伪比较。
- timeout/error 立即回退旧路径，线程和锁不会在后台堆积。
- 管理面观测和文档同步新指标，旧字段若废弃需明确兼容期。
- 最小测试：映射矩阵、unmapped、source isolation、timeout、prompt snapshot；使用 `pytest -n auto`。

## 不做什么

- 不据一次 shadow 指标切换默认召回。
- 不把 event evidence 写进 recall_trace。
- 不在本工单改变正式 prompt 内容。

