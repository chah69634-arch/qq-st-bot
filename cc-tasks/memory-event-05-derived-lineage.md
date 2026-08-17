# Brief 200 · Memory Event 05 · 派生记忆直接保存 source_event_ids

> 波次：B / 第五张，可与 MEM-04 并行
> 依赖：MEM-03
> 参考：`core/memory/mid_term.py`、`core/memory/fixation_pipeline.py`、`core/memory/episodic_memory.py`、`core/memory/storyline.py`
> 现状问题：mid-term 只有 `source_turn_id`，episodic 只有会过期的 `source_mid_ids`；storyline API 有 `source_ids`，但聚合器没有传值。

## 改法

1. mid-term 增加 `source_event_ids`，由写入时直接携带。
2. episodic 增加 `source_event_ids`，反思时从 mid-term 快照汇总，保留 `source_mid_ids` 兼容。
3. storyline inbox、weekly aggregator、`append_node()` 全链路传递来源事件 ID。
4. provenance 记录派生产物与来源事件范围，仍保持 fail-open。
5. 编写只读 lineage resolver：
   - 能从 episode/storyline node 查回事件；
   - 事件已删除或旧数据无法确认时返回 `legacy_unknown`；
   - 不根据摘要内容猜来源。
6. 对旧数据做 dry-run 统计，只有能通过 turn/source 明确匹配的才回填。

## 拍板

- `source_event_ids` 是新一等血缘字段；旧 `source_mid_ids/source_turn_id` 只做兼容。
- 不能因 mid-term 到期而丢失 episodic 的原始证据入口。
- storyline 节点继续 append-only，旧节点不得补写或改写来源；旧节点来源为空则标记未知。

## 测试

- capture → mid-term → episodic → storyline 的端到端来源链。
- mid-term 过期后 episode 仍能查回 event。
- 聚合失败、重复队列、核心去重、淘汰 inbox 和旧数据 unknown 标记。
- 现有 prompt 输出、memory isolation 和 provenance 测试：`pytest -n auto`。

## 不做什么

- 不改变 episodic/storyline 的召回排序。
- 不让来源 ID自动变成因果关系。
- 不删除 `memory_digest` 存量文件。
