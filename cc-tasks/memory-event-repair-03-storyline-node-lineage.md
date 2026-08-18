# Brief 208 · MER-03 · Storyline 节点级精确血缘

> 严重度：high / 第三张
> 依赖：MER-02；可与 MER-04、MER-05 分别施工
> 参考：`core/scheduler/triggers/storyline_weekly.py`、`core/memory/storyline.py`、`core/memory/lineage.py`

## 现状问题

weekly aggregator 把本批所有 episodic/inbox 的 `source_event_ids` 合并成一个全集，再把同一全集写进每个新 node。一个批次包含多个主题时，节点会指向与自身无关的原始事件，形成确定性的伪血缘。

## 开工前影响审计

1. 盘点 storyline 的三路材料：episodic、inbox、过滤后的 event_log；确认哪些具备可靠 event IDs。
2. 核对现有 LLM op schema、append-only 约束、失败时 cursor/inbox 的推进时机。
3. 检查旧 node、归档 arc、管理面 lineage resolver 和 provenance 的兼容读取。
4. 明确模型只能选择已提供的材料 ID，不能生成或推断 event_id。

## 改法

1. 给每条聚合材料分配稳定、短小的 `material_id`，在 prompt 中同时提供内容和该 ID。
2. `append_node` op 必须返回 `source_material_ids`；代码严格校验它们属于本批输入。
3. 由代码把材料 ID 展开为各自已落盘的 `source_event_ids`，只写到对应 node。
4. 来源不明确的 event_log 文本不得批量挂到 node；可保留 `legacy_unknown`/空来源状态，不能按摘要相似度猜测。
5. 无合法来源的 node 是拒绝、标 unknown 还是允许空来源，必须写成固定策略并反映在 lineage API。
6. provenance 记录节点最终采用的事件范围，不能记录整批未采用来源。

## 验收

- 同批两个无关主题生成两个 node，各自只能解析回自己的事件。
- 模型返回不存在、重复、超量或跨批 material ID 时不写错误血缘。
- LLM 输出失败时不推进 cursor、不清 inbox。
- 旧 node 保持 append-only，不回写猜测来源。
- lineage API 能区分 `resolved`、`legacy_unknown` 和非法来源拒绝。
- 最小测试：weekly op 解析、两主题隔离、inbox、cursor、lineage/provenance；使用 `pytest -n auto`。

## 不做什么

- 不让模型直接返回 event_id。
- 不重写历史 storyline 摘要或召回排序。
- 不把 source IDs 自动解释为因果边。

