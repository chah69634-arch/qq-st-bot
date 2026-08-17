# Brief 205 · Memory Event 10 · 历史迁移、归档、删除与媒体保留

> 波次：C / 第十张，最后执行
> 依赖：MEM-03、MEM-04、MEM-05、MEM-09
> 参考：`core/memory/event_log.py`、`core/memory/path_resolver.py`、`core/sandbox.py`、`docs/security.md`、`docs/memory.md`
> 现状问题：旧 Markdown event_log 有 30 天窗口和 full-log 轮转；媒体原文、用户遗忘语义和“原始证据永远保留”之间尚未形成一致策略。

## 改法

1. 提供 dry-run 迁移脚本，只读扫描旧 event_log、short_term、mid-term、episodic、storyline。
2. 迁移记录：总量、成功解析、结构异常、无法确认来源的 `legacy_unknown`、重复和冲突。
3. 迁移前生成备份和校验摘要；实际迁移采用小批次、可重入、可中断方式。
4. Markdown 解析无法可靠识别的消息保留原始块引用，不猜 actor、时间或因果。
5. 明确新账本 retention：
   - 原始文本；
   - 媒体文件/哈希/描述；
   - 归档数据库；
   - 关系边和派生记忆。
6. 明确“用户要求遗忘”处理：原始证据是否 tombstone、是否物理删除、关联边如何处理、管理面如何展示。
7. 更新 admin 删除接口、观测端点、备份恢复文档和三仓接口总账。

## 拍板

- 在用户明确确认 retention/遗忘政策前，不执行破坏性物理删除。
- 旧数据不可靠时宁可标 `legacy_unknown`，不能由 LLM 补造来源或因果。
- 迁移失败时旧 event_log 继续作为 fallback，不阻塞聊天。

## 测试

- dry-run 幂等、备份校验、部分失败恢复、旧新数量比对。
- Markdown 多行、伪 meta、重复块和同分钟多轮的解析回归。
- 删除/tombstone 后事件、边、派生记忆和管理面展示一致。
- `pytest -n auto`，并按 `docs/dev-environment.md` 做恢复演练。

## 不做什么

- 不在迁移时重写旧摘要。
- 不把历史事件全部重新送进 LLM 做总结。
- 不在没有备份和用户 retention 决策时删除旧文件或媒体。
