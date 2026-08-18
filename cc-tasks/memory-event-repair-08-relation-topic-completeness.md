# Brief 213 · MER-08 · 生产关系边与 Topic 完成度收口

> 严重度：medium / 最后一张
> 依赖：MER-01 至 MER-07 全部完成
> 参考：`core/memory/event_store.py`、`core/memory/fixation_pipeline.py`、`core/perceive_event.py`、`core/tag_rules.py`

## 现状问题

生产写入目前稳定生成的主要是 `previous/next/same_turn/reply_to`。`triggered_by`、`derived_from`、`correction_of`、`media_of` 虽有参数和表结构，但生产调用方没有传值；刺激事件也不一定存在于同一账本，端点校验会拒绝边。

`event_topics` 有表和读取投影，但没有生产写入者，所以角色工具返回的 topic 通常为空。默认 related 查询还会按邻居去重并只保留第一条关系，可能隐藏同一事件对之间更具体的关系。

## 开工前影响审计

1. 为每种关系列出真实生产来源、两个端点的存储位置、确定性依据和生命周期。
2. 不能为了满足表结构把外部 stimulus ID 伪装成 message event；必要时先定义只读引用节点或明确延期。
3. 核对用户更正、媒体、scheduler/sensor/watch、派生记忆和 reply_to 的现有稳定关联键。
4. Topic 只能来自规则标签或已有受控字段；小模型候选不得升级为确定 topic/事实。
5. 检查 related API/tool 是否需要聚合同一邻居的多种 relation metadata，并评估兼容性。

## 改法

1. 建立关系能力矩阵，只有端点存在且关系可由代码证明的类型才接入生产。
2. 把可确定的 relation IDs 从入口一直透传到 `capture_turn()`；跨存储端点采用显式 typed reference 设计，不能绕过悬空边守卫。
3. 媒体若没有独立 event，就不生成虚假的 `media_of`；先明确媒体引用是否需要成为事件节点。
4. Topic 首版复用纯规则 `tag_rules` 的受控标签，在 turn 边界计算一次并写入对应 event；不得新增逐轮 LLM。
5. related 返回同一邻居的完整 relation 列表，或提供兼容字段加 `relations[]`，不能只保留第一条而静默丢关系。
6. 对暂时无法可靠接线的关系在 `docs/known-issues.md` 和接口总账标 `open/roadmap`，不得宣称已完成。

## 验收

- 每一种宣称支持的关系都有至少一个真实生产入口测试，不再只由直接 `append_event()` fixture 构造。
- 无生产依据的关系不写、不中途猜测、不产生悬空边。
- 普通消息能获得受控 topic；topic 写入失败不影响原始事件。
- 同一事件对有 `same_turn + reply_to` 等多关系时，默认 related 结果不会丢失语义。
- 模型 proposal 始终与确定性 edges/topics 分表、分状态。
- 管理面、角色工具、schema 文档和三仓接口总账保持一致。
- 最小测试：各生产入口、topic 规则、related 多关系、跨 realm/source、无 LLM 热路径；tag 规则如有改动还需运行 `python tests/run_eval.py`，其余使用 `pytest -n auto`。

## 不做什么

- 不让模型候选自动升级为确定性关系或 topic。
- 不为填满字段伪造 stimulus/media 事件。
- 不改变 identity、episodic 或 storyline 的默认召回排序。

