# MCP Server 设计先行模板与 Emerald 接入参考

> 用途：开始一个新的 MCP Server 项目时，把本文复制到新仓库，改名为
> `docs/mcp-contract.md`，先填写所有 `[待填写]` 项，再开始注册工具。
>
> 本文不是 MCP 官方规范。标准字段以所用 MCP SDK 和 MCP specification 为准；本文提供的是
> PresenceKit 实际验证过的独立 Server / 通用 Client 兼容做法。

## 一、项目身份

```text
项目名称：[待填写]
Server 名称：[待填写]
版本：[待填写]
主要用途：[待填写]
状态权威源：[待填写，例如 Service + database]
支持 transport：stdio | streamable-http | sse
认证方式：none | bearer | oauth | 其他
```

### 独立性声明

本 MCP Server 必须能够被任何兼容 MCP Client 单独使用：

- 不导入 Emerald / PresenceKit；
- 不要求客户端安装本项目 SDK；
- 不要求客户端理解自定义 `_meta`；
- 不要求客户端回传工具分类；
- 不依赖相邻仓库、本机固定路径或私有 UI；
- 客户端忽略所有可选 metadata 后，`initialize → tools/list → call_tool` 仍然完整可用。

若项目确实依赖外部服务，应把它写成 Server 自己的部署依赖，而不是某个 MCP Client 的依赖。

## 二、MCP 公共表面

### 2.1 Transport

| Transport | 是否支持 | 启动/URL | 认证 | 备注 |
|---|---:|---|---|---|
| stdio | [待填写] | [待填写] | 通常无 | 不向 stdout 写非协议文本 |
| streamable-http | [待填写] | [待填写] | [待填写] | 推荐远程/常驻服务 |
| sse | [待填写] | [待填写] | [待填写] | 仅兼容需要时保留 |

同一工具在不同 transport 下必须保持相同名称、schema、metadata 和执行语义。

### 2.2 Tool 标准字段

每个 `tools/list` 条目至少应正确提供：

```json
{
  "name": "example_get_status",
  "description": "读取当前状态。",
  "inputSchema": {
    "type": "object",
    "properties": {
      "resource_id": {"type": "string"}
    },
    "required": ["resource_id"],
    "additionalProperties": false
  }
}
```

要求：

- `name` 稳定、唯一、使用 ASCII；
- `description` 说明何时调用，不写客户端品牌或 prompt 注入文字；
- 必填参数必须进入 `required`；
- 参数类型、enum、范围和长度尽量由 JSON Schema 表达；
- 不依赖模型从 description 猜必填参数；
- 修改已有参数含义属于公共契约变更，需要兼容或升版；
- 删除或改名工具前先考虑旧客户端、存量配置和调用记录。

## 三、工具目录设计

开始编码前填写：

| Tool 名称 | 用户目标 | read/write/mixed | 必填参数 | 幂等方式 | 主要失败码 |
|---|---|---|---|---|---|
| `[待填写]` | `[待填写]` | `[待填写]` | `[待填写]` | `[待填写]` | `[待填写]` |

### 3.1 工具粒度

优先一个工具对应一个清晰目标。以下情况可以使用带 `operation` 的 mixed 工具：

- 多个操作共享同一资源、版本和返回模型；
- 拆分会产生大量难以选择的小工具；
- schema 能明确表达每个 operation 的参数要求；
- Server 会在运行时再次校验 operation 与参数组合。

如果一个工具既读又写，应明确标记为 `mixed`，不要把整个工具谎报为只读。

### 3.2 有状态写工具

对数据库、游戏存档、设备任务等有状态写操作，建议评估：

```text
resource_id / game_id       目标资源
action_id / request_id      幂等标识
expected_state_version      乐观并发版本
```

这些不是所有 MCP Server 的强制标准。但如果重复提交或并发覆盖会造成问题，应在 Server 端实现，
不能只依赖客户端“尽量别重试”。

写操作应定义：

- 相同 id + 相同参数重放时返回什么；
- 相同 id + 不同参数时如何拒绝；
- stale version 如何返回；
- 超时后客户端是否可以重试；
- Server 崩溃重启后幂等记录是否仍有效。

## 四、标准 MCP Annotations

当前常用标准提示：

```text
readOnlyHint
destructiveHint
idempotentHint
openWorldHint
```

只在对该工具全部合法参数分支都成立时填写明确值。

```python
@mcp.tool(annotations={
    "readOnlyHint": True,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": False,
})
```

注意：

- annotations 是提示，不是授权；
- 客户端可以忽略它；
- mixed 工具不能为了好看错误声明 `readOnlyHint=true`；
- 远端网络、公开发布或第三方交易通常需要认真判断 `openWorldHint`；
- Server 自己仍要执行认证、权限、参数和状态校验。

## 五、可选工具分类 Metadata

MCP Tool 的 `_meta` 可以承载供应方自有的可选扩展。FastMCP 2.14.7 可通过
`@mcp.tool(meta=...)` 输出。

推荐数据形状：

```json
{
  "io.example-project/tool": {
    "schema_version": 1,
    "domains": ["observe", "project"],
    "interaction": "read"
  }
}
```

字段约定：

| 字段 | 类型 | 说明 |
|---|---|---|
| `schema_version` | integer | 当前 metadata shape 版本 |
| `domains` | string[] | 工具属于哪些任务领域；非空、去重、稳定排序 |
| `interaction` | string | `read`、`write` 或 `mixed` |

要求：

- namespace 使用 Server 供应方自己的稳定名称；
- 不冒充 MCP 官方扩展；
- 不写客户端名称；
- 不包含 token、URL secret、用户数据、资源 ID 或运行时状态；
- metadata 缺失不影响调用；
- metadata 不决定授权、确认或 effect；
- 客户端不需要把 metadata 回传给 Server。

### 5.1 真实参考

Mendel Garden 的独立实现使用：

```json
{
  "io.mendel-garden/tool": {
    "schema_version": 1,
    "domains": ["garden_action", "seed_bank"],
    "interaction": "mixed"
  }
}
```

这只是一个已验证样例，不是必须照抄的 namespace 或领域词表。

## 六、返回数据契约

### 6.1 成功结果

推荐返回结构化 JSON，而不是让客户端解析自然语言：

```json
{
  "ok": true,
  "resource_id": "opaque-id",
  "state_version": 4,
  "result": {}
}
```

按项目填写真实成功 envelope：

```json
{
  "ok": true,
  "[待填写]": "[待填写]"
}
```

### 6.2 失败结果

定义稳定错误码，使任何客户端都能根据结构处理：

```json
{
  "ok": false,
  "error": {
    "code": "STALE_VERSION",
    "message": "Resource changed; read it again before retrying.",
    "retryable": true
  }
}
```

错误清单：

| Code | 含义 | 是否可重试 | 客户端下一步 |
|---|---|---:|---|
| `[待填写]` | `[待填写]` | `[待填写]` | `[待填写]` |

不要要求客户端通过匹配中文/英文句子判断错误种类。不要在错误中返回 traceback、secret、本机
路径、数据库语句或内部对象。

### 6.3 结果大小

明确每个读取工具的分页、limit 和最大响应。大型数据应分页或摘要，不依赖客户端无限接收。

```text
默认 limit：[待填写]
最大 limit：[待填写]
最大单次结果：[待填写]
分页 cursor：[待填写]
```

## 七、认证与配置

```text
认证主体：[待填写]
凭证来源：环境变量 | secret store | 启动参数
权限模型：[待填写]
多用户隔离：[待填写或不适用]
```

基本要求：

- 示例配置只写 `${ENV_VAR}`，不提交真实凭证；
- 不把 token 放入工具 description、metadata 或结果；
- HTTP 认证失败应是明确的协议/HTTP 失败；
- stdio 场景不要依赖 HTTP header；
- Server 日志不打印 Bearer、完整敏感 URL 或调用参数中的 secret。

## 八、Emerald 接入参考

Emerald 不要求 Server 实现可选 metadata。最小接入只需要标准 MCP：

```yaml
mcp_servers:
  enabled: true
  require_local_policy: true
  servers:
    - name: example
      transport: streamable-http
      url: https://example.invalid/mcp
      headers:
        Authorization: "Bearer ${EXAMPLE_MCP_TOKEN}"
      enabled: true
      allow_tools: []
      tool_policy: {}
```

导入并明确勾选工具后，Emerald 才会生成/保存本地 allowlist 与 policy。普通新 policy 默认
`require_confirm: false`；是否确认由本地逐工具配置决定，不由 Server metadata 决定。

### 8.1 可选 Metadata Mapping

如果 Server 发布了第五节的数据形状，可以配置：

```yaml
metadata_mapping:
  namespace: "io.example-project/tool"
  schema_versions: [1]
  schema_version_field: "schema_version"
  domains_field: "domains"
  interaction_field: "interaction"
metadata_overrides:
  exact_remote_tool_name:
    mode: override               # remote | override | ignore
    domains: [local_domain]
domain_selector:
  domains: [local_domain]
  include_unclassified: true
```

Emerald 的处理规则：

- 动态工具始终保留 `category="mcp"`；
- mapping 只解释指定 namespace，不硬编码供应商；
- domains 最多 8 项，单项最多 48 字符，总长最多 256 字符；
- metadata 损坏只会失去分类，不会失去工具；
- override 按 `server + remote tool name` 精确定位；
- selector 只能收窄已经授权的工具；
- `include_unclassified: true` 保留无 metadata 的普通 Server；
- Path A 不会因为 metadata 自动获得 MCP；
- 完整 `_meta` 不落盘、不进入 prompt。

## 九、设计评审清单

编码前逐项回答：

```text
[ ] Server 离开 Emerald 后能否被标准 MCP Client 独立调用？
[ ] Emerald 离开该 Server 后能否继续连接其他 MCP？
[ ] 工具名、参数和错误码是否稳定？
[ ] mixed 工具是否如实标记？
[ ] 写工具是否需要 action_id / request_id？
[ ] 写工具是否需要 expected_state_version？
[ ] 超时后重试会不会重复产生副作用？
[ ] metadata 是否完全可选？
[ ] metadata 是否不含授权和敏感数据？
[ ] annotations 是否对所有参数分支成立？
[ ] 结果是否有界？
[ ] Server 是否在运行时重新校验参数和权限？
[ ] stdio 与 HTTP 的工具契约是否一致？
```

## 十、最低测试矩阵

### Server 仓库

```text
[ ] initialize + tools/list
[ ] 每个工具 inputSchema 快照/契约测试
[ ] 每个写工具真实 call_tool 测试
[ ] 必填参数缺失
[ ] 非法 enum / 类型 / 越界
[ ] 鉴权失败
[ ] 幂等重试（如适用）
[ ] stale version（如适用）
[ ] save/restart 后重试（如适用）
[ ] stdio 契约
[ ] streamable-http 契约（如支持）
[ ] 忽略 `_meta` 后仍可调用
[ ] metadata JSON round-trip
[ ] metadata 不含 secret 或私有状态
```

### Emerald 接入

```text
[ ] initialize + list_tools 成功
[ ] allow_tools 只包含明确授权项
[ ] 每个 allowlisted 工具有本地 policy
[ ] Tool-call Console 能用合法参数调用
[ ] Path C 暴露面符合 category / proficiency / selector
[ ] 无 metadata 时保持兼容
[ ] metadata 损坏时仍可调用
[ ] 远端 interaction 不改变本地 effect
[ ] 管理面不回显 secret 或完整 `_meta`
```

## 十一、发布前契约摘要

复制并填写后放在新 MCP 仓库的 README 或正式协议文档中：

```text
Server：[待填写]
MCP SDK / version：[待填写]
Transports：[待填写]
Authentication：[待填写]
Tools：[待填写]
Write idempotency：[待填写]
State versioning：[待填写]
Error envelope：[待填写]
Optional metadata namespace：[待填写或 none]
Metadata schema version：[待填写或 none]
Known compatible clients：[待填写]
Compatibility tests：[待填写]
```

完成这份文档不代表实现已经正确；它的作用是先固定公共契约，再让代码、测试和客户端配置围绕
同一份设计施工。
