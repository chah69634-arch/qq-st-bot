# Brief 173：Owner Turn API 接入契约、管理面观测与重启恢复

## 背景与目标

Brief 171 已经把单 active character 的完整 Reality chain 收口为共享 owner-turn application service，并提供：

- `POST /v1/owner/turns`：可信 owner 输入的幂等调用入口；
- `GET /v1/owner/turns/{client_turn_id}`：当前 token caller 自己的回合状态；
- `owner-input` scoped token profile；
- deployment capability、preflight 与 Obsidian 日记同步能力。

现在的主要缺口不是再造聊天 API，而是让后续硬件、脚本和其他本地项目能够正确接入、排障和观测：

- 接口行为分散在 router、security 文档和 OpenAPI 中，缺少一份稳定的调用者合同；
- 管理后台没有 Owner Turn API 的接入向导、调用示例、receipt 列表和异常状态摘要；
- 当前只有知道 `client_turn_id` 才能查询 receipt，不适合运维观测；
- 进程异常退出后，持久化 `running` receipt 可能永久返回 `in_flight`；
- canonical reply 的重放查询依赖“当前 active character”，切换角色后可能把仍在 retention 内的结果误报为过期。

本 Brief 的目标是补齐**标准文档、凭证接入路径、只读管理面和安全恢复语义**。不复制 Pipeline，不新增第二条
LLM/工具/记忆链。

## 已决定的产品边界

1. 外部项目接入时不是申请通用云厂商 API key，而是在 PresenceKit 管理面为每个调用方单独签发
   `profile=owner-input` 的 scoped token。
2. token label 是服务端 caller identity。同一硬件、脚本或适配器使用独立 label，不共用 desktop、mobile、device、
   panel 或 legacy admin secret。
3. 外部项目只需配置服务地址和 owner-input token；每次新的真实用户表达再生成并持久化一个
   `client_turn_id`。网络重试必须复用同一 ID 和同一 payload。
4. API 是有状态、有副作用的真实 owner turn：会写短期/长期相关状态，并可能执行当前 caller profile 允许的工具。
   不把它描述成无状态文本生成接口。
5. 首版管理面不提供无警告的“一键聊天测试台”。调用帮助以 token 签发引导、可复制示例和状态查询为主，避免管理员
   误把测试文本写进真实记忆。
6. 不允许 admin/panel token 通过一个内部旁路冒充 owner-input；需要真实调用时必须使用真实 owner-input token 走公开
   `/v1/owner/turns`。
7. 不在浏览器 localStorage、服务端日志、receipt、文档或 tracked 示例中保存完整 owner-input token。
8. `upload_ids` 当前尚无 owner-input opaque upload 签发链，标准文档必须明确“非空时固定返回
   `upload_id_not_available`”，不得把预留字段写成已经可用。

## 范围 A：建立 Owner Turn API 稳定接口标准

新增 `docs/owner-turn-api.md`，作为 Owner Turn v1 的**行为合同**；`/openapi.json` 继续作为精确 HTTP schema 真值。
`docs/api-reference.md` 必须链接该文档并登记端点、scope 与消费方。

文档至少包含以下内容。

### 连接与鉴权

- Base URL 示例只使用占位符，例如 `https://<presence-host>`；loopback 与私网/公网 TLS 边界沿用部署文档。
- HTTP 使用 `Authorization: Bearer <owner-input-token>`。
- 使用管理后台或 `POST /auth/tokens` 创建：
  `{"label":"<caller-label>","profile":"owner-input"}`。
- 明文 token 只在创建/rotate 响应中出现一次；调用项目放进 OS secret store、untracked `.env.local`、设备安全区或部署平台
  secret，不写入 Git、角色卡、Prompt、URL query、日志和截图。
- 推荐每个物理设备/程序实例独立 token label，便于单独停用、轮换和审计。
- 明确 desktop/mobile/device/panel/legacy admin token 不是 owner-input 集成凭证，普通 sensor/device 事件也不得调用本接口
  冒充用户消息。

### 请求与响应合同

- 完整列出 `client_turn_id`、`message`、`reply_to`、`upload_ids` 的类型、长度、nullable/optional 规则和示例。
- 明确禁止 body 中出现 `uid`、`char_id`、`source`、`origin`、trust、tool capability、token、配置覆盖和任何本机路径。
- 给出成功响应、202 in-flight、caller-owned status projection、completed replay、result expired、validation/auth/upstream
  错误的脱敏示例；示例必须来自当前实现或 contract fixture，不凭空发明字段。
- 固定解释 HTTP 状态：至少覆盖 200、202、401、403、404、409、410、422、429、502、503。
- 说明最终回复仍通过统一 `turn_sink` fanout；调用方不应把 HTTP body 当成另一条独立历史真相。
- 说明 owner-input 默认工具面当前仅允许既定 `info`/`memory` 类别，最终是否调用工具仍由模型 preset、角色卡和 tool-loop
  合同决定，API 可调用不等于所有工具可用。

### 幂等、超时与重试算法

提供语言无关的推荐流程：

1. 收到一条新的、真实的 owner 表达时生成稳定 opaque ID（推荐 UUID）。
2. 将 ID 与规范化请求保存在调用方 durable outbox，直到获得 terminal 状态。
3. 调用 `POST /v1/owner/turns`；客户端 HTTP timeout 不代表后端失败。
4. 收到 202、网络中断或客户端超时后，使用**同一 token、同一 ID、同一 payload**重试 POST，或 GET 查询状态。
5. 同 ID 不得修改正文、引用或上传引用；否则固定 409，调用方也不得自动换 ID 绕过冲突。
6. 只有新的用户意图才生成新 ID。代理、队列和硬件固件不得因 timeout 自动制造新回合。
7. `completed_result_expired` 表示副作用已经发生但正文已过 retention；不得重新执行。
8. `execution_outcome_unknown` 表示进程中断点无法证明副作用是否发生；必须停止自动重试并转人工/上层状态机处置。

给出 curl、PowerShell、Python 和 TypeScript 的最小示例。所有示例从环境变量或 secret provider 读取 token，并展示合理的
connect/read timeout；不得把真实 token 或本机绝对路径写进示例。

### 版本兼容规则

- `/v1` 内允许新增 optional request/response 字段和新增固定错误码；调用方应忽略不认识的 response 字段。
- 删除/改名字段、改变既有字段类型、改变幂等键或副作用语义属于 breaking change，必须新增版本路径或迁移期。
- OpenAPI schema、本文档和 Brief 172 canonical protocol fixtures 必须互相校验；发现冲突时以运行代码为发布真值并登记文档
  drift，不能让三个客户端各自维护一份协议猜测。

## 范围 B：管理后台“接口与部署”页面

在管理后台“工具与连接”分组新增“接口与部署”页面，建议包含三个页签：

1. **Owner Turn API**
   - 显示 base URL（只显示当前可公开 origin，不拼接 credential）、method/path、认证 profile 和版本；
   - 展示请求字段、安全提示、curl/Python/TypeScript 可复制模板；
   - 提供“前往 Token 管理”入口，并显示 owner-input token 的 label、disabled、过期时间和 hash 短前缀；
   - 创建/rotate 仍复用现有 Token 管理合同，明文只展示一次；本页不得重新读取完整 token；
   - 按 `client_turn_id` 查询 caller status 的示例与解释，不要求 panel token 冒充 caller。
2. **运行观测**
   - 最近 receipt 列表、状态分布、异常 `running/interrupted_unknown/failed` 摘要；
   - caller label、client turn ID、canonical turn ID、status、created/updated、固定 error code；
   - status/caller/time 过滤和有界分页；
   - 不显示请求 hash、用户正文、assistant reply、Prompt、工具参数/结果、token 或路径。
3. **部署与同步**
   - 聚合现有 deployment capability、deployment preflight、桌面 WS 最近状态和 diary sync status；
   - 明确区分 configured、online、last-success 与真实 E2E verified，不把静态绿色配置写成链路已通过。

页面遵循现有管理面 fragment、i18n、action binding 和静态缓存版本规则：修改 fragment 时同步
`ADMIN_UI_FRAGMENT_VERSION`、`core.js?v=`；新增/修改直载 JS/CSS 时同步 `index.html` 查询版本。

### 调用测试台边界

首版不增加 admin-only 代理执行端点，也不让 panel token 获得 owner-input 身份。若未来确需页面内真实 smoke：

- 必须另开窄范围 Brief；
- 使用调用者临时粘贴的 owner-input token，只保存在当前页面内存，不进 localStorage/日志；
- 调用公开 `/v1/owner/turns`，不得走内部 executor；
- 执行前二次确认“这是真实 owner message，会写记忆并可能调用工具”；
- 默认使用 test sandbox/合成角色，而不是生产 owner 数据。

## 范围 C：脱敏 receipt 观测端点

新增只读端点，建议：

```text
GET /observability/owner-turns?status=<status>&caller=<label>&limit=<n>&cursor=<opaque>
```

要求：

- 使用 `state.read`；不改变现有 caller-owned `GET /v1/owner/turns/{client_turn_id}` 安全边界。
- 返回有界、稳定排序、可分页的 metadata projection；默认 limit 较小并设硬上限。
- caller 过滤只接受合法 token label；cursor 为服务端 opaque 值，不接受任意路径或文件名。
- 观测结果只含本 Brief B 列出的安全字段，不含 request hash 或任何对话内容。
- receipt store 仍走 `core.sandbox.get_paths()`、原子写和有界 retention；观测不得把目录遍历暴露成 API。
- 页面加载失败 fail-open，不影响聊天主链；列表扫描不得阻塞 owner turn 的关键锁。

## 范围 D：重启中断与 canonical replay 修复

### 持久 `running` 恢复

严格 exactly-once 无法跨“外部工具/LLM 已产生副作用、completed receipt 尚未原子落盘”的崩溃窗口凭空保证。本 Brief
采用 fail-closed 的 outcome-unknown 语义：

- 进程启动时或首次读取 receipt 时，若持久 `running` 不属于当前进程 `_INFLIGHT` task，则原子转成 terminal
  `interrupted_unknown`，固定错误码 `execution_outcome_unknown`。
- 同 caller + client_turn_id 后续 POST 不得重新运行 LLM、工具或记忆写入；返回文档定义的固定非成功状态。
- 不提供“强制重试同 ID”按钮。人工确认要产生一条新 owner message 时才允许用新 ID；这必须是新的产品意图，不是自动
  timeout retry。
- 当前进程中仍真实存在的 `_INFLIGHT` task 继续返回 202，不得被年龄阈值误杀。
- `running` 不再永久逃过 retention；只有当前活 task 可以受保护，历史 interrupted receipt 按普通有界策略保留。
- preflight 与管理面显示 interrupted count，但不自动清理或改写真实历史。

### canonical reply 定位

- completed replay 必须以 receipt 的 canonical `turn_id` 定位，不能只搜索“当前 active character”的 short-term。
- 角色切换后，只要 canonical turn 仍在既有 retention 内，应返回同一 reply/turn ID；过期后才返回
  `completed_result_expired`。
- receipt 仍不保存 assistant reply。若需要增加最小 scope pointer/index，必须是 metadata-only、经 DataPaths、原子写、
  有界 retention，并且不通过观测端点泄露角色私有内容。
- 不创建第二份聊天历史或第二个 turn sink；优先扩展现有 canonical turn lookup/index。

## 范围 E：凭证签发与“填入其他项目”的操作手册

接口标准文档和管理面必须把实际接入步骤写成可执行清单：

1. 在 Token 管理创建唯一 label，例如 `<integration-name>`，profile 选择 `owner-input`。
2. 立即复制只显示一次的 `emt_...` token 到目标项目的 secret store；关闭页面后无法再次读取，只能 rotate。
3. 在目标项目配置 `PRESENCE_BASE_URL` 与 `PRESENCE_OWNER_TOKEN`（名称仅为推荐示例，不是协议字段）。
4. 调用 `/auth/whoami` 做不泄密身份自检，确认 label/profile 对应的 scope 含 `chat`；不得打印完整 token。
5. 实现 durable `client_turn_id`、202/timeout 查询和固定错误码处理后，再接真实硬件输入。
6. 对麦克风/按钮输入做本地去抖和“用户真实表达”判定；普通传感器事实继续走 sensor/device 通道。
7. token 泄露或设备丢失时在管理面立即 disable/rotate；不同调用方独立 token，避免全端一起换钥。

不得指导用户把 token 填进 tracked `config.yaml`、代码常量、角色卡或任意 URL。本仓示例配置只保留占位符。

## 不在范围内

- 不新增通用 OpenAI-compatible `/chat/completions` 外观；PresenceKit owner turn 的状态、幂等和副作用合同不能被抹掉。
- 不新增匿名/公开聊天、多租户、任意 char_id 选择或 caller 自选工具类别。
- 不新增第二条 Pipeline、第二套 conversation lock、第二个 memory writer 或 admin 内部直调 LLM。
- 不实现 owner-input 媒体上传；`upload_ids` 非空继续 fail loud，后续由独立 Brief 建立 opaque upload ownership。
- 不修改 desktop/mobile 现有聊天协议，不把普通 device/sensor token 升级为 chat token。
- 不在本 Brief 修改 Intiface/Buttplug、TTS、NapCat、MCP transport 或代理策略。
- 不把管理面 receipt 列表做成聊天历史浏览器。

## 预计主要文件

后端：

- `core/owner_turn_service.py`
- `core/owner_turn_receipts.py`
- `admin/routers/owner_turn.py`
- 新的 owner-turn observability router，或现有 observability router 的窄扩展
- `admin/admin_server.py`
- `admin/static/index.html`
- `admin/static/pages/` 新接口与部署 fragment
- `admin/static/js/` 新页面逻辑
- `admin/static/js/core.js`
- `admin/static/js/i18n.js` 及现有语言资源
- `docs/owner-turn-api.md`（新，v1 行为合同）
- `docs/api-reference.md`
- `docs/security.md`
- `docs/feature-control-surface.md`
- `docs/runtime-lifecycle.md`

## 验收标准

1. 一个新项目只阅读 `docs/owner-turn-api.md` 和 OpenAPI 即可正确创建 owner-input token、提交 turn、处理
   202/timeout/retry、查询状态并安全轮换凭证，不需要阅读 Python 实现猜协议。
2. 管理面能展示 API 接入模板、owner-input token metadata、receipt 状态和 deployment/diary 摘要；不显示完整 token、正文、
   Prompt、工具结果、请求 hash或本机路径。
3. admin/panel/device/sensor token 不能调用 owner turn；owner-input token 不能获得 admin、device、desktop、hardware 权限。
4. receipt 列表端点有 scope、分页、过滤、硬上限和稳定排序，不能跨越 DataPaths 或读取任意文件。
5. 进程重启后遗留 `running` 不再永久 202，也绝不自动重跑；返回固定 `execution_outcome_unknown` 并进入可观测 terminal 状态。
6. 当前进程真实 in-flight duplicate 仍返回 202；同键不同 payload 仍固定 409；completed duplicate 仍不产生第二次副作用。
7. 切换 active character 后，retention 内 completed turn 仍能按 canonical turn ID 重放；确实过期时才返回 410。
8. API 文档、OpenAPI、代码错误码和示例一致；`upload_ids` 未实现状态被明确写出。
9. 管理面中英文可切换，fragment 与直载静态资源 cache version 已更新，无新增 inline handler/CSP 回归。
10. 不修改现有 desktop/mobile owner chain 语义，不新增平行 LLM/tool/memory 路径。

## 验证

- 后端 focused `pytest -n auto`：auth/profile、serial/concurrent duplicate、payload conflict、当前 in-flight、重启
  interrupted、retention、active-character switch replay、result expired、观测分页/过滤/scope/脱敏。
- 管理面 focused static/UI checks：导航、fragment 加载、i18n、复制模板、Token 页面跳转、API 失败态、receipt 空态/分页/过滤。
- 运行 `/openapi.json` 与文档示例的 contract check；示例不得包含真实 token、用户名、角色名、邮箱或本机绝对路径。
- 使用合成 test sandbox 做一次 owner-input token create → whoami → POST → 202/GET 或 completed → duplicate replay → rotate
  smoke；不得写生产 owner memory。
- `git diff --check`，并检查所有新增文档/fixture 不含完整 `emt_` token 或本机路径。
- 未完成真实重启窗口验证与管理面实际浏览器 smoke 时，本 Brief 只能标记 `partial`。

## 建议施工顺序与提交边界

1. 定稿 `docs/owner-turn-api.md`、错误码与版本规则，补 contract tests，独立后端 commit。
2. 修复 interrupted receipt 与 canonical replay，补 focused tests，独立后端 commit。
3. 增加脱敏 receipt observability endpoint，补 scope/分页/retention tests，独立后端 commit。
4. 增加管理面“接口与部署”页面、i18n 和静态缓存版本，独立后端 commit。
5. 合成 sandbox smoke、重启验证和文档差异收口，独立证据/文档 commit。

每阶段完成相关测试和差异检查后立即提交，不夹带当前 Dream、release、桌面 UI 或其他并行改动。
