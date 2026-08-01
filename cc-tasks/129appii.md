你现在接手 PresenceKit / Emerald-presence 的 OpenAI Responses API 协议适配。

项目目录：

<仓库路径>

当前问题：

部分模型中转站只提供 OpenAI Responses API，例如其 Codex 导入配置明确使用：

```toml
wire_api = "responses"
```

但 PresenceKit 当前不存在 Responses API 分支。

目前仓库行为：

* provider / preset 没有明确的 API 协议字段
* `provider_kind: openai` 只决定客户端类型，不决定调用协议
* 模型注册统一构造 `AsyncOpenAI`
* 普通聊天和 tool loop 都固定调用：
  `client.chat.completions.create(...)`
* tool loop 在 `core/llm_client.py` 中默认把返回值当作 OpenAI `ChatCompletion`
* 仓库内没有 `client.responses.create(...)`
* 当前部分 GPT / Claude 中转在 tool loop 中报 502，实际底层可能是响应结构不兼容后触发的 AttributeError，而不是 prompt、API key 或 FastAPI 问题

已确认的当前配置关系：

* `gpt-claude` 是 routing profile，不是 provider 或 preset
* 当前 `gpt-claude.chat` 指向 `gpt`
* `gpt` 使用 `provider_kind: openai`
* `claude-pig` 使用：

  * `provider_kind: anthropic_compat`
  * `tool_call_mode: function_calling`
* 上述配置均未声明 `chat_completions` 或 `responses`

本工单目标：

为模型 preset/provider 增加显式 API 协议选择，并为 OpenAI Responses API 实现最小可用适配，使普通聊天和现有原生 tool loop 能根据协议正确调用。

不要通过伪造 `.choices` 对象硬塞进现有逻辑。协议差异应在清晰的适配边界中处理。

一、先只读审计

在修改代码前，确认并记录：

1. 模型配置从 YAML/JSON 到 `ModelClient` 的完整解析链
2. `AsyncOpenAI` 的构造位置
3. 普通聊天、原生 tool loop、流式输出分别从哪里发起请求
4. 当前内部代码真正依赖的模型响应字段：

   * assistant 文本
   * finish reason / completion status
   * tool call ID
   * tool name
   * tool arguments
   * usage
   * reasoning 或 metadata
5. `tool_call_mode` 与 `provider_kind` 当前分别承担什么职责
6. 当前是否真的启用了 SDK streaming；不要仅根据变量名猜测

先给出简短审计结论，再进行实现。

二、配置层

增加显式协议字段，名称建议：

```yaml
api_protocol: chat_completions
```

允许值至少包括：

```text
chat_completions
responses
```

要求：

* 未声明时保持现有行为，默认 `chat_completions`
* 不改变现有 provider/preset 的运行结果
* `provider_kind` 继续表示供应商或兼容类型
* `api_protocol` 只表示实际调用的 API 协议
* 不要让 `tool_call_mode` 隐式决定 API 协议
* 未知协议值必须 fail-fast，报出 provider、preset/model 和非法值
* 配置应能够在具体 preset 上覆盖 provider 默认值；仅在当前配置架构确实支持继承时实现，不要另造复杂继承系统

三、协议适配边界

建立一个小而明确的协议适配层，避免把大量：

```python
if api_protocol == ...
```

散落在 tool loop、普通聊天和路由逻辑中。

可以根据现有架构选择文件位置和命名，但应形成类似职责：

```text
模型请求构建
→ 按 api_protocol 调用 SDK
→ 将协议响应归一化为 PresenceKit 内部结果
→ 上层聊天/tool loop 消费统一结果
```

内部归一化结果至少需要表达：

```text
assistant_text
tool_calls[]
finish/status
usage
raw_response（仅用于诊断，不进入持久化）
```

每个 tool call 至少包含：

```text
id
name
arguments
```

`arguments` 的内部约定应统一。若当前 tool loop 期望 JSON 字符串，则适配器保持该约定；若当前内部已经使用 dict，则在协议边界解析。不要让同一字段有时是字符串、有时是 dict。

四、Chat Completions 分支

现有行为必须继续可用：

```python
client.chat.completions.create(...)
```

要求：

* 普通文本回复不回归
* 原生 function calling 不回归
* 现有模型和 DS 路由不受影响
* 不因新增适配器改变现有 prompt、消息顺序或工具 schema
* 不顺手重写 routing profile、preset 或模型参数系统

五、Responses API 分支

当：

```yaml
api_protocol: responses
```

时使用：

```python
client.responses.create(...)
```

根据当前安装的 OpenAI Python SDK真实类型实现，不要凭印象猜字段。

需要适配：

1. 输入消息

把当前 PresenceKit 的 system/developer/user/assistant 上下文转换为 Responses API 接受的输入结构。

必须保持：

* 消息顺序
* system/developer 指令边界
* 用户文本
* 工具结果与对应 call ID
* 多轮 tool loop 上下文

不要把全部历史粗暴拼成单个字符串。

2. 工具 schema

把当前 Chat Completions 使用的 function tool schema 转换为 Responses API 所需 schema。

保持工具名称、描述、参数 JSON Schema 与权限逻辑不变。

不要修改工具注册、权限确认、MCP 调度或工具执行层。

3. 响应解析

从 Responses API 的 `output` 项中正确提取：

* assistant 文本
* function call
* call ID
* function name
* arguments
* completion/incomplete 状态
* usage（SDK 提供时）

不要假设 Responses API 存在：

```python
response.choices[0].message
```

4. tool loop 回填

工具执行完成后，必须按 Responses API 要求把 function call output 回填到下一轮请求，并维持原 call ID。

不要把工具结果伪装成普通 user 文本。

现有 tool loop 的：

* 最大轮数
* 权限检查
* confirmation
* MCP 调用
* outcome_unknown
* ephemeral tool status
* 最终自然语言 assistant turn

均不得改变。

5. 流式输出

先核实当前代码是否依赖真实 token streaming。

如果现有主链并没有真正消费 SDK stream，本工单只实现非流式 Responses API，不要凭空扩张范围。

如果 Responses 模型配置请求了当前尚未支持的 streaming，应明确报错或显式回落到非流式；不可静默读取错误结构。

只有在现有主链确实必须依赖 SDK streaming 时，才实现 Responses streaming，并为以下事件建立明确状态机：

* text delta
* function call arguments delta
* output item completed
* response completed
* response failed/incomplete

六、错误处理

修复当前防御缺口。

调用完成后，在读取响应字段前验证协议和响应类型。

错误信息至少区分：

* 网关 HTTP 请求失败
* 返回对象与声明协议不匹配
* Responses output 中没有可消费内容
* 工具调用 arguments 非法
* 未知 `api_protocol`
* SDK 版本不支持 `responses`

错误应包含安全的诊断信息：

```text
provider
preset/model
api_protocol
response type
HTTP status（若有）
```

不得记录：

* API key
* Authorization header
* 完整用户对话
* 完整工具结果
* 敏感 raw response body

面向前端的错误不应再表现为无解释的 AttributeError 502。可以返回现有错误结构，但消息应明确类似：

```text
模型网关返回格式与配置的 API 协议不兼容
```

七、配置示例

为该中转增加或提供一个不含密钥的示例 preset，例如：

```yaml
provider_kind: openai
api_protocol: responses
model: gpt-5.5
base_url: https://api.deralive.top
tool_call_mode: function_calling
```

实际字段名和层级应服从项目当前配置结构。

不要直接覆盖现有 `gpt` preset，避免影响当前正常路由。新增独立测试 preset 或文档示例即可。

注意：

Codex TOML 中的：

```toml
wire_api = "responses"
```

不能直接作为 PresenceKit 配置字段读取。PresenceKit 使用自己的 `api_protocol` 字段明确表达相同语义。

八、测试

至少增加以下测试。

配置测试：

1. 未声明 `api_protocol` 时默认 `chat_completions`
2. 显式 `responses` 正确传入模型客户端
3. 非法协议 fail-fast
4. routing profile 解析后仍能保留最终 preset 的协议
5. `provider_kind` 不会覆盖或猜测 `api_protocol`

Chat Completions 回归测试：

1. 普通文本回复仍从 Chat Completions 解析
2. function call 仍能进入现有工具执行链
3. tool result 后能够生成最终 assistant 回复
4. DS 或现有可用 preset 不回归

Responses API 测试：

1. 普通文本 output 正确归一化
2. 单个 function call 正确解析
3. arguments 正确处理
4. 工具结果以 function call output 形式回填
5. 多轮工具调用能够继续
6. 最终自然语言回复仍是唯一正式 assistant turn
7. 无 output 或未知 output item 时给出明确错误
8. 返回 ChatCompletion 对象但声明为 responses 时明确报协议不匹配
9. 返回 Responses 对象但声明为 chat_completions 时明确报协议不匹配
10. usage 缺失时不崩溃

错误测试：

1. 不再因缺少 `.choices` 抛裸 AttributeError
2. 网关错误不会泄露 API key 或完整响应正文
3. SDK 无 `responses` 能力时给出明确升级/不支持信息

使用 fake client / stub response，禁止测试依赖真实中转、真实 API key 或网络。

九、非目标

本工单不要：

* 重构整个 model registry
* 修改 routing profile 语义
* 删除或替换 Chat Completions
* 修改 prompt builder
* 修改工具权限、确认策略或 MCP 协议
* 修改 Dream 独立链路，除非它复用了同一个模型调用适配器且无需额外行为变化
* 将 Claude 原生 Messages API 一并纳入
* 把 `anthropic_compat` 自动解释为 Responses API
* 为所有第三方网关做猜测式兼容
* 根据模型名称猜协议
* 静默 fallback：声明 `responses` 后失败，不得偷偷改走 Chat Completions；反之亦然
* 为了通过测试伪造 OpenAI SDK 类型或在生产代码中 monkey patch `.choices`

十、验收标准

完成后应满足：

* 旧配置不改即可继续走 Chat Completions
* 新 preset 能显式选择 Responses API
* Responses 普通聊天可工作
* Responses function calling 能完成“模型请求工具 → 执行工具 → 回填结果 → 最终自然语言回复”
* 正式 assistant turn、记忆写入和 turn sink 语义不变
* 协议不匹配时给出明确错误，不再裸抛 AttributeError
* 不影响 DS 和现有正常模型
* 无密钥、敏感 URL 参数或用户内容进入仓库
* 相关单元测试通过
* `git diff --check` 通过
* Python 语法检查通过

完成后请汇报：

1. 审计确认的真实调用链
2. 最终配置字段与默认行为
3. 协议适配层放置位置
4. Responses tool loop 如何回填 call output
5. 修改文件列表
6. 测试命令及结果
7. 尚未覆盖的限制
8. commit hash

先审计，再做最小适配。若发现当前 OpenAI SDK 版本不支持 `client.responses.create`，先报告依赖版本和最小升级范围；不要直接无边界升级全部依赖。
