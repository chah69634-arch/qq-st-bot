# Brief 195 · Memory Event 00 · 基线与不变量

> 波次：A / 第一张，必须串行
> 依赖：无
> 参考：`AGENTS.md`、`docs/memory.md`、`ARCHITECTURE.md`、`docs/interaction-event-model.md`、`cc-tasks/00d-研究备忘-长期记忆Fragment-Event聚合评估.md`
> 现状问题：当前 `turn_id` 是整轮血缘键，不是逐消息事件键；event_log、mid-term、episodic、storyline 之间没有稳定的原始证据回溯闭环。

## 改法

只增加测试、样例和审计文档，不改运行时行为。

1. 在 `tests/` 建立统一记忆链 fixture，覆盖：
   - 普通 owner chat；
   - scheduler/stimulus assistant-only turn；
   - QQ/desktop/mobile 入口；
   - 图片/文件消息；
   - Dream、Stage、web/coplay 隔离；
   - 两个角色的同一 uid。
2. 固化旧链路的 golden 结果：
   - `fetch_context()` 返回的层和字段；
   - `event_log.search()`、`episodic.retrieve()`、`short_term.load_for_prompt()` 的结果形状；
   - `recall_trace` 的字段；
   - `turn_id` 与 transport `msg_id` 的既有关系。
3. 建立回归断言：新工单在默认关闭时不得改变上述结果。

## 拍板

- 本工单不生成 `event_id`，不建数据库，不改 prompt。
- golden fixture 中的内容使用占位文本，不写真实用户数据、token 或本机路径。
- 失败标准优先看数据边界和行为变化，不以“测试数量增加”代替验收。

## 测试

- `pytest -n auto` 指定新增 fixture 和现有 memory/pipeline/turn_sink 相关测试。
- 至少有一个跨角色、Dream 隔离和媒体消息回归用例。
- 运行 `git diff --check`，确认只新增任务/测试文件。

## 不做什么

- 不修现有 bug；修复放到 MEM-01。
- 不创建新数据文件。
- 不让任何新 fixture 被生产 prompt 读取。
