# Brief 206-213 · Memory Event Ledger 审查修复批次

> 状态：completed / MER-01..10 已关闭
> 最终提交：MER-10 post-gate 原子提交
> 前置：Brief 195-205 已实现，但尚不能按完整事件链验收
> 目标：先消除默认聊天路径风险和错误证据，再恢复灰度功能，最后补齐关系与主题能力。

## 开工前统一要求

每张工单开始前必须先读 `AGENTS.md`、`docs/memory.md`、`docs/dev-environment.md`，并按改动面补读
`docs/runtime-lifecycle.md`、`docs/interaction-event-model.md`、`docs/security_model.md`、`docs/tools.md`。

每张工单都必须先做只读影响审计，至少回答：

1. 改动是否位于 send 前关键路径，最坏等待时间是多少。
2. 是否改变 `short_term/event_log/mid_term/episodic/storyline` 旧链路或默认 prompt。
3. uid、char_id、realm、stream、source 是否仍被冻结并显式透传。
4. 重试、乱序写入、重复写入、部分失败和进程重启后是否仍幂等。
5. 管理面、角色工具、shadow、迁移脚本和调度器哪些消费者会受到影响。
6. 是否需要观测字段、配置开关、接口文档或客户端降级提示。

禁止用“账本是附加功能”跳过延迟和数据正确性检查。原始证据、确定性关系和派生血缘一旦错误，后续查询不得通过总结或模型猜测修补。

## 执行顺序

```text
MER-01 发送前热路径与顺序边算法
  ↓
MER-02 QQ 媒体证据保真
  ↓
MER-03 storyline 节点级血缘 ─────┐
MER-04 source 隔离策略 ──────────┤
MER-05 历史迁移解析与路径覆盖 ───┘
  ↓
MER-06 候选边调度器发现修复
  ↓
MER-07 shadow 新旧对比口径
  ↓
MER-08 生产关系边与 topic 收口
```

MER-03、04、05 在 MER-02 后可分别施工，但仍须各自测试、检查差异并独立提交。MER-08 必须最后执行，避免在底层边和隔离规则未稳定前继续增加写入者。

## 工单与审查发现映射

| 工单 | 主问题 | 默认路径风险 |
|---|---|---|
| MER-01 | 每次 append 全库重建边、乱序后保留旧邻接边 | 高 |
| MER-02 | QQ 媒体把 OCR/抽取文本当 raw evidence，缺媒体哈希 | 高 |
| MER-03 | 每个 storyline node 绑定整批来源 | 高 |
| MER-04 | web/dream_echo/coplay 可经事件工具重新进入上下文 | 高 |
| MER-05 | 迁移漏 assistant，且不覆盖现行角色级日志 | 高 |
| MER-06 | 调度器查错 SQLite 文件名 | 中 |
| MER-07 | 新旧召回使用不同 ID 空间计算 overlap | 中 |
| MER-08 | topic 无生产写入者，多类确定性关系无生产接线 | 中 |

## 提交纪律

每张工单完成相关测试和差异检查后立即创建独立 Git commit，再开始下一张。不得把迁移、热路径、召回策略和 UI 修改塞进同一个提交。默认不运行全量测试；按 `docs/dev-environment.md` 使用指定测试文件和 `pytest -n auto`。

## 最终结论

MER-01..08 的独立提交、MER-09 闸门与 MER-10 post-gate 纠偏均已完成。MER-09 后的
只读复核曾重开关闭结论；MER-10 补齐 Markdown 正式召回隔离、真实 migration dry-run、
storyline 双来源 cursor v3、并行有界 shadow、proposer 双端 source policy 及失败观测后，
以 focused 回归和差异闸门重新关闭。未接生产入口的关系类型仍按 roadmap 管理。
