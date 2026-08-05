# Brief 137：通用 MCP 可选分类元数据消费与本地映射

## 一、目标

让 Emerald 可以读取第三方 MCP Tool 的可选 `_meta` 分类信息，用于管理面展示和本轮工具筛选，
同时保持对所有普通 MCP Server 的兼容。

Emerald 是独立开源 MCP Client。本工单不得硬编码 Mendel Garden、某个供应商名称或某个仓库
路径，不得要求 MCP Server 提供分类后才能连接或调用。

核心原则：

```text
没有 metadata：正常使用
metadata 未识别：正常使用
metadata 损坏：忽略该工具的远端分类，正常使用
metadata 可识别：作为可选筛选提示
本地 policy：始终决定授权和执行
```

## 二、内部模型

动态 MCP 工具继续注册为：

```text
category = "mcp"
```

不得用远端 domain 替换 `_TOOL_REGISTRY.category`，否则现有
`tool_loop.categories`、角色 `presence_ext.tool_categories`、MCP proficiency 和旧配置会失效。

为动态工具增加独立、安全摘要字段，命名由实现者按本地风格决定，语义至少包括：

```text
remote_domains: list[str]
remote_interaction: read | write | mixed | unknown
metadata_source: none | remote | local_override
metadata_status: absent | recognized | unrecognized | invalid | overridden
metadata_schema_version
```

这些字段只用于展示和暴露面收窄，不得改变：

```text
allow_tools
tool_policy.effect
require_confirm
idempotent
origin gate
参数 schema 校验
MCP 连接状态
角色熟练度
```

## 三、禁止供应商锁定

不得出现以下实现：

```python
if server_name == "mendel_garden": ...
if "io.mendel-garden/tool" in meta:  # 唯一硬编码支持路径
```

Emerald 应提供通用的每 server metadata 映射配置。建议结构语义：

```yaml
mcp_servers:
  servers:
    - name: example
      metadata_mapping:
        namespace: "io.example/tool"
        schema_versions: [1]
        domains_field: "domains"
        interaction_field: "interaction"
```

字段名可以按现有配置风格调整，但必须满足：

- 每个 MCP Server 可使用自己的 namespace；
- 未配置 mapping 时不猜测授权或 effect；
- 管理员可对单个工具设置本地 domain override；
- 本地 override 优先于远端 metadata；
- 删除 mapping/override 后回到普通 `mcp` 行为；
- 配置不包含或复制远端 secret；
- 一个 Server 的映射失败不影响其他 Server。

可以提供少量“已知数据形状”的纯结构解析 helper，但不能把供应商名称写成业务分支。若为方便
导入提供自动建议，它必须要求管理员确认采用哪个 namespace，且不获得任何授权效果。

### 3.1 已落地的独立 Server 参考契约

独立开源 MCP Server Mendel Garden 已在提交 `cff5409` 中实现以下实际 `tools/list` 扩展。
下例省略了与本议题无关的完整 description 和 input schema，`annotations` 与 `_meta` 结构取自
真实契约：

```json
{
  "name": "mendel_seed_bank",
  "description": "...",
  "inputSchema": {"type": "object", "properties": {}},
  "annotations": {
    "idempotentHint": true,
    "openWorldHint": false
  },
  "_meta": {
    "io.mendel-garden/tool": {
      "schema_version": 1,
      "domains": ["garden_action", "seed_bank"],
      "interaction": "mixed"
    }
  }
}
```

其中分类 payload 的权威 shape 是：

```json
{
  "schema_version": 1,
  "domains": ["非空、去重、稳定排序的字符串"],
  "interaction": "read | write | mixed"
}
```

当前实际 domain 词表为：

```text
account
archive
breeding
care
game_lifecycle
garden_action
observe
research
seed_bank
```

`mendel_seed_bank` 和 `mendel_research` 是实际的 `mixed` 示例；标准 MCP annotations 与 `_meta`
分类彼此独立。Emerald 不得用 `interaction` 覆盖 annotations，也不得用二者覆盖本地 policy。

这份契约用于：

- 给实现者一个真实的 MCP Tool JSON 样例；
- 作为 mapping 配置和解析测试 fixture；
- 完成一次可选的跨仓人工兼容验证。

它不得变成运行时供应商特判。Emerald 的通用实现必须通过如下配置解释该输出：

```yaml
mcp_servers:
  servers:
    - name: local_garden
      metadata_mapping:
        namespace: "io.mendel-garden/tool"
        schema_versions: [1]
        domains_field: "domains"
        interaction_field: "interaction"
```

换成其他 namespace、相同字段形状的第三方 MCP Server 后，同一解析器必须照常工作。未填写这段
mapping 时，Mendel Garden 也必须继续作为普通 `category="mcp"` Server 被发现和调用。

## 四、解析边界

在 `list_tools()` 成功之后、动态注册表条目生成之前解析 `_meta`。

要求：

1. `_meta` 缺失：`metadata_status=absent`。
2. namespace 缺失：`metadata_status=unrecognized`，工具仍注册。
3. 值不是 object：`metadata_status=invalid`，工具仍注册。
4. schema version 不支持：忽略分类，工具仍注册。
5. domains 不是字符串数组、过长、数量过多或含控制字符：忽略非法值。
6. interaction 未识别：记为 `unknown`，不得据此生成 effect。
7. 单个工具异常不得中止该 server 的其他工具注册。
8. 不持久化完整 `_meta`；只保留有长度上限的安全摘要。

为 domains 设置明确上限，例如：

```text
最多 8 项
单项最多 48 字符
总长度有界
```

不要把远端 metadata 原样拼进 LLM prompt、日志或管理面 HTML。

## 五、本地覆盖

管理面允许管理员为已发现工具设置本地逻辑 domain。该覆盖只影响筛选和显示。

至少支持：

```text
使用远端分类
本地覆盖分类
忽略远端分类
```

本地覆盖必须按 `server + remote tool name` 定位，不按动态注册后的拼接名字模糊匹配。

工具消失、server 断线或重连时保留 authored override；工具再次出现时重新应用。工具改名后不得
把旧 override 自动套给新工具。

## 六、暴露面筛选

保持现有第一层：

```text
category includes "mcp"
→ MCP allow_tools / local policy
→ connection / registry
→ proficiency
→ exclude_tools
```

只有第一层已经允许 MCP 后，才可以用逻辑 domain 继续收窄：

```text
mcp 已允许
→ optional domain selector
→ 本轮 tools schema
```

domain selector 只能减少已授权工具，不能扩大工具集合。

未配置 selector 时保持旧行为：所有通过现有 MCP 门控的工具均可见。配置了 selector 时：

- 有匹配 domain 的工具可见；
- 无 metadata 的工具如何处理必须显式配置，默认建议 `include_unclassified=true` 以保证兼容；
- 引用了不存在的 domain 不能导致整个 server 断连；
- Path C 和 relay 必须看到同一个已经筛选后的 schema；
- Path A 仍不得因为 metadata 自动扩大到 MCP 类别。

不要把第三方 MCP 动态工具塞入现有“内置工具 preset”持久清单。若需要 MCP domain preset，应使用
独立配置，避免把某次连接快照误当作稳定工具目录。

## 七、管理面与观测

MCP 管理面按工具展示三个彼此独立的状态：

```text
已发现
已授权
当前会话可暴露
```

并显示安全摘要：

```text
远端 domains
本地 override
最终 domains
interaction 提示
metadata 状态/版本
未分类或解析失败提醒
```

必须明确写出：

- 远端分类不是授权；
- `interaction` 不是本地 effect；
- 未分类工具仍可通过普通 MCP 兼容路径使用；
- 是否确认由本地 policy 控制。

扩展现有 MCP 设置/观测端点，不新增无观测落盘物。端点只返回安全摘要，不返回完整 `_meta`、
headers、URL secret、Bearer、原始 description 或完整参数 schema。

修改直接加载的 JS/CSS 或页面 fragment 时，遵守 Admin Static Asset Cache 版本规则。

## 八、第三方兼容测试

测试不得只使用 Mendel Garden fixture。至少构造以下独立 Server：

1. 无 `_meta` 的标准 MCP Server。
2. 使用任意其他 namespace 的合法 metadata Server。
3. `_meta` 值类型错误的 Server。
4. schema version 未知的 Server。
5. 一个坏工具和一个正常工具并存的 Server。
6. metadata 声称 read，但本地 policy 是 write 的 Server。
7. metadata 声称某 domain，但没有 allowlist 授权的 Server。

验收：

- 全部 Server 均能完成 initialize/list_tools；
- 无 metadata 的 Server 行为与本工单前一致；
- 坏 metadata 不阻断工具注册与 `call_tool`；
- 远端分类不能改变本地 effect/confirm；
- domain selector 只能收窄；
- `include_unclassified=true` 保持旧 Server 可用；
- 本地 override 可覆盖任意 namespace 的 Server；
- Path C 与 relay schema 一致；
- 管理面不泄露完整 `_meta`。

另增加一个可选的跨仓契约测试或人工验证说明，使用任意实现了同一 JSON shape 的 MCP Server
验证；不能让 Emerald 测试套件依赖相邻仓库存在。

测试仓内可以保存一个由上述实际输出精简得到的静态 fixture，但 fixture 不得包含相邻仓库绝对
路径、凭证、运行时 game id 或完整远端业务结果。该 fixture 只证明通用 mapping 能解释真实
shape，不能替代无 metadata、其他 namespace 和坏 metadata 测试。

## 九、文档与控制面

至少更新：

- `docs/tools.md`
- `docs/model-presets.md`
- `docs/feature-control-surface.md`
- MCP 管理面相关说明
- `config.example.yaml` 或等价配置示例

文档必须说明这是客户端可选扩展，不是 MCP 官方分类标准。第三方 MCP 无需实现即可被 Emerald
使用；第三方客户端也无需理解这些配置即可使用原 MCP Server。

## 十、非目标

本工单不得：

- 硬编码 Mendel Garden server、namespace 或工具名；
- 要求 MCP Server 安装 Emerald SDK；
- 修改 MCP 标准 transport；
- 用远端 metadata 自动生成 allow_tools、effect 或 confirmation；
- 将完整远端 `_meta` 注入 LLM；
- 默认排除所有未分类 MCP 工具；
- 把 `category="mcp"` 改成远端 domain；
- 修改 Path A 以默认暴露 MCP；
- 新增参数相关风险预检；
- 修改无关记忆、scheduler、Stage 或通道协议。

## 十一、施工与验证

实现前按 AGENTS.md 阅读：

```text
docs/tools.md
docs/model-presets.md
docs/security.md
docs/dev-environment.md
```

若修改 MCP 生命周期或 registry，再读：

```text
docs/runtime-lifecycle.md
docs/interaction-event-model.md
docs/security_model.md
```

优先跑 MCP、tool loop、settings 和管理面相关测试，使用 `pytest -n auto`、指定路径或
`pytest --testmon`，不要串行跑全量。

完成相关测试、静态资源版本检查、`git diff --check` 后提交一个独立 commit。只暂存本工单
实际修改的相关文件，不得提交或回滚工作区已有无关改动。

## 十二、交付报告

```text
metadata mapping 配置结构
解析与 fail-soft 位置
动态 registry 安全摘要字段
本地 override 存储位置
domain selector 接线位置
Path C / relay 一致性
管理面三态展示
第三方无 metadata / 坏 metadata 测试
相关测试结果
git diff --stat
commit hash
剩余 dirty files
```
