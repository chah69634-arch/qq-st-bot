# Brief 133: Sensor Judge 独立模型路由与失败韧性

来源：2026-08-04 `SILENT_TOGETHER` 裁决调用 `/responses`，SDK 连续重试后返回 `502 Upstream access forbidden` 的运行日志审计。

## 目标

让低价值、后台运行的 sensor 裁决使用稳定、低延迟、可独立治理的模型路径；上游拒绝或故障时快速 fail-closed，并把失败完整计入既有 API 调用总账。

## 已确认根因

当前活跃 routing profile 把 `intent` 指向使用第三方网关 `responses` 协议的 preset。`sensor_judge` 固定解析 `intent`，因此一次后台裁决会触发 SDK 自动重试，并最终收到上游权限型 502。事件 prompt、JSON 解析和 `SILENT_TOGETHER` 规则本身不是根因。

## 实现要求

### 1. 独立 routing category

新增明确的轻量调用类别：

```text
sensor_judge
```

`core.scheduler.sensor_judge.judge()` 必须解析该 category，不再复用通用 `intent`。

所有内置/示例 routing profile 必须显式声明 `sensor_judge`；默认指向稳定的轻量 `chat_completions` preset。若用户自定义旧 profile 未声明该字段，兼容回退顺序必须明确且有测试，建议：

```text
sensor_judge → intent → chat
```

不得根据模型名猜测协议，也不得在单次 502 后静默把 Responses 请求改成 Chat Completions。

### 2. 后台调用重试/超时策略

为 `sensor_judge` 提供独立、保守的调用策略：

- SDK 自动重试为 0，或最多 1 次短重试
- 设置短于主聊天的明确 timeout
- 失败保持当前 fail-closed 语义：返回不主动发言的裁决结果
- 不因失败占用 conversation lock
- 不阻塞主消息 send 路径

策略应通过模型 client/request policy 的集中接口表达，不在 `sensor_judge.py` 临时修改 SDK 私有字段。

### 3. 可分类失败

至少区分并记录：

```text
timeout
auth_or_forbidden
rate_limited
upstream_5xx
transport
response_format
```

对 `Upstream access forbidden` 应归为 `auth_or_forbidden` 或更精确的 `upstream_forbidden`，用于观测和后续熔断；不得把上游原始响应正文直接展示给用户。

### 4. 失败观测接入既有总账

失败调用必须写入 `core/api_call_log.py` 的既有按日总账，并通过现有：

```text
GET /observability/api-calls
```

可查询。至少记录：

- caller/category=`sensor_judge`
- preset/provider/model
- protocol
- duration
- `ok=false`
- 安全的错误分类

不得记录 prompt、屏幕文本、API key、完整上游响应或 Authorization header。既有端点已经满足 AGENTS.md 对落盘台账的只读观测要求，不另建平行日志。

### 5. 熔断边界

实现一个小而明确的进程内 circuit breaker，作用域至少包含 preset/category：

- 连续出现权限型或上游 5xx 达阈值后短时 open
- open 期间 sensor judge 直接 fail-closed，不再打上游
- 冷却后允许一次 half-open 探测
- 成功后清零
- 状态只需进程内，不新增落盘状态

阈值与冷却应有保守默认值和测试。不要为本 Brief 建完整通用服务网格。

### 6. 设置控制面

若新增 routing category 或调用策略配置，必须同步：

- `docs/model-presets.md`
- `docs/feature-control-surface.md`
- desktop `docs/settings-control-audit.md`
- 管理面实际展示/编辑逻辑（如果该页面枚举 routing categories）

不得只改 `config.yaml` 形成只在当前机器生效、发行配置不知道的新语义。

## 相关文件

- `core/scheduler/sensor_judge.py`
- `core/model_registry.py`
- `core/llm_protocol.py` / `core/llm_client.py`（按现有边界选择）
- `core/api_call_log.py`
- `admin/routers/settings_llm.py`
- `config.example.yaml` 或当前发行配置模板
- `docs/model-presets.md`
- `docs/feature-control-surface.md`
- `tests/test_model_presets.py`
- sensor judge 与 API call log 相关测试
- `../Emerald-client/docs/settings-control-audit.md`（如控制面受影响）

## 测试

至少覆盖：

1. `sensor_judge` 解析 `sensor_judge` category
2. 旧 profile 缺字段时按规定回退到 `intent`
3. 内置 profile 显式配置该 category
4. sensor policy 不执行主聊天级连续重试
5. timeout/403/429/502/格式错误均 fail-closed
6. 失败不会进入主动消息生成
7. 失败 API 调用写入总账，且 `ok=false`、错误分类正确
8. 总账不包含 prompt、screen hints、key 或完整上游 body
9. circuit breaker 达阈值后不再调用上游
10. half-open 成功后恢复
11. 主聊天及其他 category 的 retry/timeout 行为不受影响
12. 设置 API 往返后新 category 不丢失

## 非目标

- 不修复或绕过第三方网关权限
- 不把上游凭据写入日志
- 不让 sensor 失败自动切换 API protocol
- 不为 sensor failure 向用户发送错误消息
- 不修改 `SILENT_TOGETHER` 触发阈值或 prompt 内容

## 验收

- sensor judge 不再依赖通用 `intent` 的高能力/高延迟 preset
- 上游 forbidden 时快速结束，不出现长串 SDK 重试
- 失败可从既有 observability endpoint 查到
- circuit breaker 可阻止持续打坏上游
- 配置、管理面和文档语义一致
- 相关后端测试并行通过
- 涉及 desktop 文档/控制面时，desktop 测试与 build 通过
- 两仓分别 `git diff --check` 通过
- 后端独立 commit；如改 desktop，desktop 独立 commit，并互相回填 hash
