# Brief 196 · Memory Event 01 · 现有 scope 与 retention 缺陷

> 波次：A / 第二张，必须串行
> 依赖：MEM-00
> 参考：`core/tool_dispatcher.py`、`core/memory/event_log.py`、`core/scheduler/loop.py`、`docs/memory.md`
> 现状问题：`get_episodic` wrapper 没有透传当前 `char_id`；`cleanup_event_log()` 没有 `char_id`，调度器实际只维护默认角色。

## 改法

1. `core/tool_dispatcher.py`：
   - `_get_episodic_wrapper()` 接收并透传当前角色 scope；
   - dispatcher 的 memory read 分支统一检查 `uid + char_id`；
   - 不允许用默认角色作为非默认角色的隐式 fallback。
2. `core/memory/event_log.py`：
   - `cleanup_event_log()` 增加显式 `char_id`；
   - 内部所有写/归档路径使用该角色 scope。
3. `core/scheduler/loop.py`：
   - retention 维护遍历已注册角色，或复用现有角色枚举 helper；
   - 单个角色失败不得阻塞其他角色。
4. 搜索仍保持原有输出格式，不趁此工单修 scoring。

## 拍板

- 这是独立 bugfix，不依赖新事件账本。
- 对无法解析 active character 的路径继续 fail-loud，不回落到硬编码角色。
- retention 不改变默认天数、归档份数和 full-log 大小，只修 scope 覆盖。

## 测试

- 补非默认角色 `get_episodic` 读取测试。
- 补两个角色分别归档、互不删除测试。
- 运行既有 tool dispatcher、memory isolation、scheduler maintenance 测试：`pytest -n auto`。

## 不做什么

- 不改事件 schema。
- 不改变 recall 排序、时间窗口或 prompt 层。
- 不顺手修 event-log Markdown 解析；那属于账本迁移范围。
