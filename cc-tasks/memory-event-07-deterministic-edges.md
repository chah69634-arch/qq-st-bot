# Brief 202 · Memory Event 07 · 确定性关联边

> 波次：C / 第七张，必须串行
> 依赖：MEM-02、MEM-03、MEM-05
> 参考：`core/memory/event_store.py`、`core/turn_sink.py`、`core/perceive_event.py`、`docs/interaction-event-model.md`
> 现状问题：当前没有结构化关系边；把上一条、同一轮、回复对象等确定关系交给模型会增加不必要的不确定性。

## 改法

1. 代码生成以下边：
   - `previous` / `next`；
   - `same_turn`；
   - `reply_to`；
   - `triggered_by`；
   - `derived_from`；
   - `correction_of`；
   - `media_of`。
2. 边字段包含：`from_event_id`、`to_event_id`、`relation_type`、`origin=system`、`confidence=1`、`created_at`、`schema_version`。
3. 边写入必须幂等，事件写入失败时不能产生悬空边。
4. `get_related_events` 首版只读这些边。
5. 提供 edge counts、悬空边、重复边和失败写入的只读观测。

## 拍板

- 确定性边不调用 LLM。
- 事件删除/脱敏后，边保留 tombstone 或被标记 dangling，不静默指向新事件。
- `previous/next` 只在同一 uid/char/realm/stream 内建立，不能跨梦境或跨角色串联。

## 测试

- 顺序追加、并发追加、重复追加、跨 turn 回复关系。
- trigger、media、source-isolated turn 和 realm 边界。
- 删除/脱敏后的 dangling edge 行为。
- `pytest -n auto`，并检查旧聊天路径不受影响。

## 不做什么

- 不增加语义相似边。
- 不改变 prompt 或 episodic 排序。
- 不允许管理员直接改写边作为临时补丁。
