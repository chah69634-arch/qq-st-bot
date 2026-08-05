# Brief 136：统一 QQ/Desktop 前置工具路由与 Probe 契约

## 一、背景与产品前提

PresenceKit 是单用户陪伴系统。本工单按以下产品优先级实施：

```text
便捷性 > 防止用户误操作
```

不要把多人平台、企业后台或不可信租户系统的默认安全策略直接套进本项目。
管理员已经明确加入白名单的工具，应优先做到直接可用、少打断。

当前工具链存在两个不必要的通道差异：

```text
QQ：关键词快路径 → probe → execute
Desktop/Mobile 前台：probe → execute
```

两边最终都调用 `core.tool_dispatcher.execute()`，但前置判断逻辑分别写在
`main.py` 和 `admin/routers/chat.py`。这造成行为、测试和观测重复，也容易让后续工具只在
一个通道生效。

另一个容易误解的点是 `xml_fallback`。它不是第三条完整工具 Path，也不是让小聊天模型
直接控制工具。它只是 `llm_client.chat(..., tools=...)` 在模型不支持原生 function calling
时，用 XML 表达一次工具判断结果的编码方式。

本工单不重写 Path C，不把所有模型统一成同一种工具决策方式。

## 二、目标行为

### 2.1 小模型 / 非 Path C

```text
QQ / Desktop / Mobile 用户消息
→ 共用前置工具路由
→ 可选的确定性零参数快速匹配
→ 未命中则调用独立 probe
→ 后端解析工具名和参数
→ dispatcher 执行
→ 只把执行结果注入聊天 Prompt
→ 聊天模型生成最终回复
```

聊天模型不得看到 probe 原始输出，也不得依靠自己输出 `<tool_call>` 来执行工具。

### 2.2 高能力模型 / Path C

继续保留现有原生 function-calling 多步 loop：

```text
主聊天模型原生 tool call
→ dispatcher 执行
→ tool result 回填
→ 下一步调用或最终回复
```

不要把 Path C 改成统一 probe。现有多步调用、MCP、relay、状态事件和工具结果续接语义保持不变。

## 三、统一前置工具路由

新增一个通道无关的前置路由入口，供 QQ 与 `/desktop/chat` 共用。具体模块位置由实现者按现有
所有权边界决定，但不得继续在两个入口复制 probe 和 execute 循环。

统一入口至少接收：

```text
trusted_user_text
uid
char_id
channel / provenance_channel
target_id
is_group
session_state
是否启用 Path C
```

统一返回结构化结果，不要只返回一段自然语言：

```text
route: fast_match | probe | skipped_for_tool_loop | no_tool
tool_calls
tool_results
prompt_tool_result
confirmation_request（如有）
missing_parameter_request（如有）
tools_available
```

QQ 和 Desktop 可以保留不同的可见类别，例如 desktop 通道可见 `desktop` 类，而不具备桌面
能力的通道只见 `info`。这属于共用路由的输入策略，不应继续形成两套实现。

群聊、owner 身份、active character、全局工具开关和现有 `execute(origin=)` 闸门不得被绕过。

## 四、快速匹配

将 QQ 专属 `_fast_path_match()` 收进共用前置路由。

快速匹配只允许用于满足全部条件的工具：

```text
零必填参数
无外部副作用
关键词低误触
显式进入快速匹配 allowlist
```

当前 `get_time` 可以保留。QQ 和 Desktop 对同一句“几点了”应产生相同路由结果。

不得把所有 `_TOOL_REGISTRY.keywords` 自动当作快速执行规则。`keywords` 仍主要用于 probe 提示；
快速执行必须使用独立、明确的 allowlist。

Path C 激活且快速工具成功执行时，继续确保本轮 loop 不重复调用同一工具。快速执行失败时允许
Path C 再尝试一次，并在观测数据中区分 `fast_failed_then_loop_retry`。

## 五、明确 XML Probe 契约

保留 XML 作为不支持 function calling 的 probe 模型适配方式，但明确以下硬契约：

1. XML 只在独立 probe / relay 意图解析调用中使用。
2. Path A 的主聊天生成不得携带 `tools` schema。
3. probe 原始文本不得注入主聊天 prompt、assistant history、通道输出或 TTS。
4. XML 解析失败、JSON 参数损坏、未知工具名时，按“没有可靠工具调用”处理。
5. 解析失败不得把 `<tool_call>` 原文当作普通聊天内容返回。
6. probe 原文可以进入现有受控观测，但必须继续遵守观测端点的 scope 和长度限制。

评估将内部命名或文档措辞从含混的“XML 工具路径”改成“XML probe encoding / XML probe
adapter”。不要求为了改名进行大范围无价值重构。

`run_agentic_loop()` 内现有 tail-brace relay 仍可使用 probe 解析，但它必须继续复用本轮已经筛选
后的 `tools` 集合，不能扩大 MCP 或其他类别暴露面。

## 六、确认与参数补充策略

按单用户、便捷优先原则调整默认策略。

### 6.1 必须区分两类询问

```text
missing_parameter_request：工具缺少执行所需参数
confirmation_request：工具参数完整，但策略要求再次确认
```

不能继续把两者都模糊为 `ask_text` 后由调用方猜测。可以在不破坏过多调用方的前提下增加
结构化状态或兼容包装，但最终路由结果必须能明确区分。

缺参数追问必须保留，因为没有参数时工具无法正确执行。

### 6.2 默认确认策略

- 普通内置工具默认直接执行。
- 管理员明确加入 MCP `allow_tools` 且已有有效本地 policy 的工具，默认
  `require_confirm: false`。
- `read`、`write`、`actuate` 不应仅因 effect 名称就自动逐次确认。
- 保留管理员对单个工具显式设置 `require_confirm: true` 的能力。
- 只有项目已经明确认定为不可逆或代价明显的操作，才建议默认确认，例如真实删除、付款、
  对外公开发布等。
- `unrestricted` 的现有含义保持不变。

更新 MCP 默认 policy 生成逻辑、批量授权逻辑及管理面说明，使新导入并明确白名单授权的工具
默认不确认。旧配置中用户显式写出的 `require_confirm` 不得被迁移覆盖。

不要削弱以下边界：

```text
MCP allow_tools
本地 tool_policy 存在性
工具 enabled
origin 合法性
参数 schema 校验
角色/通道暴露面
MCP 连接与注册状态
```

这里简化的是“是否每次再问一遍”，不是取消白名单和执行条件。

## 七、结果与失败语义

统一路由必须能区分：

```text
no_tool_selected
tool_executed
tool_failed
tool_unknown
arguments_invalid
missing_parameters
confirmation_required
probe_parse_failed
probe_unavailable
```

不要靠解析中文结果字符串判断执行是否成功。若当前 `execute()` 无法提供足够的结构化结果，
本工单允许为它增加兼容的结构化返回层，但不得一次性重写所有工具实现。

probe 故障应 fail-soft：本轮继续普通聊天，不因工具判断模型不可用而让用户无法对话。

## 八、观测

复用或扩展现有 probe capture / tool trace，QQ 和 Desktop 输出同一结构。至少可观察：

```text
channel
route
fast_path_matched
probe_used
probe_encoding: function_calling | xml
tools_available_count
selected_tool
execution_status
fast_failed_then_loop_retry
confirmation_required
missing_parameters
```

不得落盘 MCP secret、headers、完整敏感参数或不受限的原始工具结果。

如果新增落盘字段或新台账，必须按 AGENTS.md 同单提供只读观测端点；若只是扩展现有 probe capture
和 tool trace，则扩展现有端点即可。

## 九、文档与控制面同步

至少更新：

- `docs/tools.md`
- `docs/channels.md`
- `docs/model-presets.md` 中 `xml_fallback` / `tool_call_mode` 的说明
- `docs/known-issues.md` 中 QQ 快路径重复调用的过时描述
- `docs/feature-control-surface.md`

若修改管理面 MCP 默认确认展示或文案，还要按 Admin Static Asset Cache 规则更新静态资源版本。

## 十、测试

先读 `docs/dev-environment.md`，使用相关测试或 `pytest --testmon`；不要默认串行跑全量。

至少覆盖：

### 通道一致性

- QQ 与 Desktop 对 `get_time` 快速匹配结果一致。
- 两个通道未命中快速匹配时调用同一个前置路由实现。
- 通道类别差异通过参数表达，不复制 probe 实现。
- Path C 激活时跳过普通 probe，但快速工具结果仍能进入 prompt。
- 快速工具成功后 Path C 不重复调用。
- 快速工具失败后 Path C 可以重试并留下明确观测。

### XML 隔离

- XML probe 正确解析工具名和参数。
- XML 缺闭合标签、非法 JSON、未知工具时不执行工具。
- 解析失败后继续普通聊天。
- probe XML 原文不进入主聊天 messages、assistant history、通道输出或 TTS。
- Path A 主聊天调用不携带工具 schema。
- relay 只能解析本轮已暴露工具。

### 确认与参数

- 缺少必填参数时返回 `missing_parameter_request`，不会误执行。
- 白名单 MCP 默认 policy 为 `require_confirm: false`。
- 用户显式配置 `require_confirm: true` 时仍要求确认。
- 旧配置中已有显式确认设置不会被导入或批量授权覆盖。
- 未进入 allowlist、无本地 policy、origin 非法或 schema 参数不合法时仍被拒绝。
- QQ 与 Desktop 对确认请求、参数补充请求的行为一致。

### 回归

- Path C 原生多步 function calling 不退化。
- MCP relay、tool preset、角色 `tool_categories` 和 proficiency 过滤不扩大暴露面。
- probe 异常不阻断普通聊天。

## 十一、非目标

本工单不得：

- 删除 Path C；
- 让小聊天模型直接输出 XML 控制工具；
- 新增“先选类别、再调用第二次主模型”的两阶段协议；
- 默认把 `memory`、`fs`、`system` 或 MCP 全量暴露给 Path A；
- 取消 MCP allowlist 或本地 policy；
- 把远端 MCP description/category 当作本地授权；
- 顺手重写整个 dispatcher 或所有工具返回值；
- 修改无关 scheduler、memory 或 prompt 层。

## 十二、施工顺序与提交

建议按以下顺序完成，并在相关测试、差异检查通过后提交一个独立 commit：

```text
1. 建立结构化前置路由结果与共用入口
2. QQ / Desktop 接入共用入口
3. 收拢快速匹配
4. 补 XML 隔离与失败语义
5. 简化 MCP 默认确认策略
6. 更新观测、文档和管理面文案
7. 跑 focused tests、git diff --check、检查 dirty worktree
8. 提交独立 commit
```

## 十三、交付报告

完成后报告：

```text
git status --short
git diff --stat
commit hash
共用前置路由入口
QQ / Desktop 接线位置
快速匹配的新归属
XML probe 隔离方式
confirmation 与 missing parameters 的区分方式
MCP 默认 policy 变化
新增或扩展的观测字段
相关测试结果
未运行或失败的验证及原因
```
