# Brief 195–205 · Memory Event Ledger 系列工单总览

> 状态：ready / 讨论已拍板，尚未开始实现
> 目标：在不替换现有记忆链的前提下，增加可追溯的事件证据账本、只读展开能力和候选关联边。
> 原则：先观测，再双写，再只读使用，最后才允许影响 prompt。

## 全系列开工前必读

- `AGENTS.md`
- `docs/memory.md`
- `ARCHITECTURE.md`
- `docs/runtime-lifecycle.md`
- `docs/interaction-event-model.md`
- `docs/security_model.md`
- `docs/dev-environment.md`
- 与当前工单直接相关的 `docs/tools.md`、`docs/three-repo-interface-catalog.md`

## 执行顺序

```text
MEM-00 基线与不变量
  ↓
MEM-01 现有 scope/retention 缺陷
  ↓
MEM-02 事件账本 schema 与存储适配器
  ↓
MEM-03 capture_turn/turn_sink 双写
  ↓
MEM-04 查询 API 与管理面观测 ─┐
MEM-05 派生记忆 source_event_ids ─┘
  ↓
MEM-06 角色只读事件工具
  ↓
MEM-07 确定性关联边
  ↓
MEM-08 模型候选关联边
  ↓
MEM-09 shadow recall 与 prompt 灰度
  ↓
MEM-10 历史迁移、归档、删除与媒体保留
```

MEM-04 与 MEM-05 在 MEM-03 完成后可并行；其余按箭头串行。

## 全系列硬约束

1. 新功能默认关闭；旧 `short_term/event_log/mid_term/episodic/identity/storyline` 路径继续可用。
2. 新事件账本写失败必须 fail-open，不能阻塞聊天、发送、队列或现有记忆写入。
3. Dream、Stage、web/coplay 等来源必须按 realm/source 隔离，不能因为新查询 API 变成跨域召回。
4. 新落盘状态必须提供 scoped 只读观测入口；不得只写文件不提供验证面。
5. 新记忆写入或派生关系写入必须记录 provenance；原始证据不可由 LLM 摘要覆盖。
6. 每张工单开始前执行调用链、scope、锁、幂等、TTL、回放和跨端闭环检查。
7. 相关测试使用 `pytest -n auto`；通过后立即创建独立 Git commit，再开始下一张工单。
8. 涉及客户端协议时同步三仓接口总账；若本阶段没有客户端消费方，明确标记为 backend/admin-only。

## 总体非目标

- 不一次性替换 event_log。
- 不把 identity、user_facts、mood 或 mid-term 删除。
- 不让小模型直接改写事件、事实或确定性因果边。
- 不在事件账本尚未完成 shadow 对比前改变默认 prompt 行为。
