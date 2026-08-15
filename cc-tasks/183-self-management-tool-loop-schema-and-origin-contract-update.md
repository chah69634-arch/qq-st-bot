# Brief 183: Self Management 工具 schema、tool loop 过滤与 origin 合同更新

## 背景

Tool loop 相关 7 个失败来自 Brief 级新能力已落地、旧测试仍按旧集合断言：

- `manage_self_capability` 被安全地加入 schema，但旧测试期待只有 web/MCP tools；
- `manage_self_capability.action` 缺少参数 description，属于真实 schema 缺陷；
- execute origin 已新增 `assistant_self_management`、`autonomy_self_management`、`autonomy_loop`，旧 allowlist
  审计仍冻结旧值；
- Author Note 与 Prompt scope spy 未接收 `generated_at` / `tool_result_status` 新参数。

## 施工范围

- 为 `manage_self_capability` 每个参数补完整 description，并通过工具 schema 通用审计。
- 明确该 gateway 在什么条件下自动加入 Path C/autonomy schema；`exclude_tools`、preset narrowing、角色能力关闭
  必须仍能排除它。测试不得无条件把额外工具视为失败，也不得让 gateway 绕过显式 exclude。
- 更新 origin freeze 测试为分层 allowlist：用户/assistant loop、self-management、autonomy；逐项断言每个 origin
  只能执行对应工具面，不能仅比较集合。
- 更新测试 spy 签名并断言 `generated_at`、validity、`tool_result_status` 的传播语义；不要从生产调用中删除这些
  grounding 字段。
- 核对 self-management audit 不持久化 MCP URL、header、token 或 raw payload，保持 known issue SCM-1 守卫。

## 验收

- `test_tool_loop.py`、`test_tool_schema_descriptions.py`、`test_intent_grounding.py`、
  `test_r5_author_note_tool_alignment.py`、`test_scope_freeze_r1_n1_n10.py` 通过。
- 普通 unknown origin 继续 fail-closed；新增 origin 不能扩大普通角色/普通工具权限。
- 更新 `docs/tools.md`、`docs/security_model.md` 与 self capability 控制面文档。

