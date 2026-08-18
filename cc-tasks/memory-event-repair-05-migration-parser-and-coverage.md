# Brief 210 · MER-05 · 历史迁移解析与现行路径覆盖

> 严重度：high / 第五张
> 依赖：MER-01；可与 MER-03、MER-04 分别施工
> 参考：`core/memory/event_migration.py`、`core/memory/event_log.py`、`scripts/migrate_memory_events.py`

## 现状问题

迁移解析器把 `speaker` 当成整块字段。正常 user+assistant 块首先命中 `speaker:user`，导致 assistant 行被跳过；因为 user 已成功解析，该块也不会记为 unknown。

默认扫描目录只指向 uid-only legacy event_log，不扫描当前 `data/runtime/memory/{char_id}/{uid}/event_log`。short-term、mid-term、episodic、storyline 当前只计数，不导入或建立引用，因此 dry-run 容易给出“资产存在”但账本历史仍为空的误导结果。

## 开工前影响审计

1. 收集当前 writer 实际产生的 Markdown 块、旧版本块、trigger assistant-only 块、多行内容、伪 meta 和同分钟多轮样例。
2. 明确 current/legacy 两个目录的 union 和去重规则，不能重复迁移同一 turn。
3. 对 short/mid/episodic/storyline 明确“只盘点”还是“迁移”，并让 CLI、报告和文档使用同一措辞。
4. 核对备份、批次状态、source digest 和中断恢复在多来源扫描后的稳定性。

## 改法

1. 解析 actor 时使用与每条消息相邻/对应的 meta，不使用整块第一个 speaker。
2. 优先用同块 `turn_id + actor` 生成确定 ID；缺失或冲突时使用稳定块引用并标 unknown，不猜显示名。
3. 默认扫描 current 和 legacy Markdown，按既有 union 语义去重；报告分别给出 current/legacy/duplicate 数量。
4. 对其余四类资产：
   - 若本阶段只扫描，报告字段必须明确为 `inventory_only`，不得计入可迁移 total；
   - 若能由已存 turn/source_event_ids 确定关联，只建立确定引用；
   - 不根据摘要正文反推原始消息。
5. source digest 必须覆盖实际参与迁移的所有来源及相对标识，文件新增/修改后安全重新规划。
6. 保持旧文件不删除、失败可重入、迁移批次有已验证备份。

## 验收

- 真实 user+assistant 块迁移出两条事件并保留同一 turn 关系。
- assistant-only trigger、同分钟多轮、多行、伪 speaker、重复 current/legacy 块结果正确。
- 默认 dry-run 能发现当前角色级 event_log，不只发现 uid-only 目录。
- 报告区分 inventory、parsed、unknown、duplicate、conflict 和 failed。
- 部分失败恢复后数量与一次性迁移一致，旧 fallback 始终可读。
- 最小测试：迁移矩阵、数量对账、备份校验、中断恢复；使用 `pytest -n auto`，按 `docs/dev-environment.md` 做恢复演练。

## 不做什么

- 不由 LLM 重建历史 actor、时间或因果。
- 不因迁移完成删除 Markdown、媒体或旧摘要。
- 不把盘点数量伪装成已导入事件数量。

