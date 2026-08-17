# Brief 201 · Memory Event 06 · 角色只读事件工具

> 波次：B / 第六张，必须串行
> 依赖：MEM-04、MEM-05、MEM-01
> 参考：`core/tool_dispatcher.py`、`docs/tools.md`、`core/pipeline.py`、`admin/scopes.py`
> 现状问题：角色只有 `get_episodic`，没有事件窗口/关联事件读取；memory 工具默认不走 Path A，Path C 也默认关闭。

## 改法

1. 注册只读工具：
   - `expand_event_window(event_id, before=10, after=10)`；
   - `get_related_events(event_id, relation_types, cursor, limit)`；
   - 必要时增加 `search_events` 作为 seed 入口。
2. 工具结果必须带：`event_id`、时间、actor、topic/source、turn_id、relation metadata、证据正文。
3. dispatcher 统一透传 `uid + char_id + realm`，复用 MEM-01 的 scope 修复。
4. 每次调用限制最大事件数、最大文本字符数、最大关系深度和游标页数。
5. 只读工具走现有 tool grounding 和 execution origin 闸门；失败返回结构化 unknown，不生成伪成功文本。
6. 在工具 trace 中记录调用、scope、截断、失败原因和耗时；不把原文写入 action_trace 或 short_term。

## 拍板

- 首版只在 Path C function-calling owner private turn 中可见，默认总开关关闭。
- 不自动把整段事件链注入 prompt；只有角色主动调用才返回。
- `expand` 是确定性邻接读取；`related` 首版只读取确定性边。

## 测试

- 工具 schema、参数边界、scope、确认/origin 闸门和 tool grounding。
- 角色切换、Dream/Stage 禁止访问 Reality 事件。
- 工具失败、超时、结果截断和 tool loop disabled 的降级。
- `pytest -n auto`，补现有 tool dispatcher char-scope 回归。

## 不做什么

- 不开放写、修订、遗忘事件工具。
- 不在 Path A 直接扩大 memory 工具暴露面。
- 不让工具调用触发新的事件或记忆固化。
