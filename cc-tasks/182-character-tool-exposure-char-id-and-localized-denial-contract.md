# Brief 182: 角色工具暴露面、char_id 贯通与本地化拒绝合同

## 背景

工具能力与通道组有 13 个失败，包含一个明确运行时错误：`channels/desktop.py` 使用未导入的
`is_remote_server()`。其余失败集中于 per-char `tool_categories` 覆盖未贯通、phone-control debug status
与 shared exposure resolver 不一致、desktop probe 参数丢失，以及角色权限观测集合新增 `mcp` 后旧测试漂移。
MCP proficiency 与 toy safe-mode 还向用户返回了英文 capability fallback。

## 施工范围

- 修复 Desktop 文件降级路径的 `is_remote_server` 导入/依赖，覆盖 local、remote、WS unavailable、behavior
  fallback 和 optional `char_id`。
- `Pipeline.run_agentic_loop()`、Path A probe、phone-control debug、character permissions 全部复用
  `core.tool_exposure.resolve()`，不得各自重新解释 `presence_ext.tool_categories`。
- 明确 legacy `tool_categories` 只覆盖 Path C；Path A 使用 `tool_categories_path_a`。测试按该正式合同构造角色卡。
- 冻结并断言 desktop probe 的 `location`、categories、allowed tool names、profile/history `char_id` 来自同一轮
  frozen scope，不在中途重新读取 active character。
- phone-control debug 在角色缺少 category 或 load failure 时 fail-closed，三个 enabled 字段均不得误报 true。
- character-permissions 的 `_ALL_CATEGORIES` 是否包含 `mcp` 以当前产品能力为准；若已正式支持则更新 schema
  测试和 UI 文档，不删除新类别以迎合旧集合。
- 建立统一、中文可见的 capability denial reason 映射，区分 safe mode、角色未授权、MCP proficiency 未解锁；
  不向用户泄漏内部等级、policy 或英文内部错误。

## 验收

- 本组列出的 channel/presence_ext/phone-control/external-tool/observability/MCP/toy tests 全部通过。
- Desktop fallback 不再抛 `NameError`；remote server 不写本地 fallback queue。
- 角色卡覆盖、Path A/Path C、观测接口和用户拒绝文案对同一配置给出一致结果。
- 同步 `docs/tools.md`、`docs/channels.md`、控制面与三仓接口总账。

