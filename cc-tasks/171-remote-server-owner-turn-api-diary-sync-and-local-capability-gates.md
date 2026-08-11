# Brief 171：远程服务器单角色 Turn API、用户日记同步与本机能力闸门

## 背景与目标

PresenceKit 当前准备把后端长期运行在远程服务器，通过私网隧道或 HTTPS/WSS 内网穿透供桌面、手机和
后续硬件访问。系统仍是单用户、单 active character 的有状态陪伴后端，不改造成无状态 LLM 网关。

当前代码已经有共享单角色链：`admin/routers/chat.py::run_owner_chat_turn()` 被
`POST /desktop/chat` 与 `POST /mobile/chat` 复用，覆盖 conversation gate、角色 scope freeze、
上下文/记忆读取、Prompt、探针或 Path C 工具循环、LLM、`turn_sink`、关键记忆写入、慢队列和通道
fanout。本 Brief 要做的是把这条真实链变成稳定的 application service 与可重试 API，而不是复制
Pipeline 或另建平行聊天系统。

服务器化还改变了“本机”的含义：后端进程中的 `127.0.0.1`、绝对路径、关机/休眠、文件 fallback
都指向服务器，不再指向用户电脑。必须区分：

- **桌面动作**：后端经 `/ws/desktop` 下发 action，Tauri 前端在用户电脑执行并 ack；远程 WS 在线时
  仍然有效，应保留。
- **服务器本机能力**：Python 后端直接操作所在 OS、后端文件系统或旧桌面绝对路径；服务器模式下应
  fail-closed。

## 已决定的产品边界

- 后端、NapCat 同机部署；本 Brief 不迁移或重构 QQ/NapCat。
- Intiface/Buttplug 已冻结；不修改其协议、任务系统、工具实现或 UI。本 Brief 只在部署预检中确认其
  维持关闭，不把它作为服务器化验收项。
- TTS 不在本 Brief 范围，不迁移、不修复、不验收。
- 不新增统一 EventBus、EventEnvelope、客户端 MCP 协议或第二套记忆系统。
- 不迁移、删除、覆盖真实 `data/`、`userdata/` 或用户 Obsidian 原文件。
- 现有 `/desktop/chat`、`/mobile/chat`、`/ws/desktop`、`/ws/device` 协议保持兼容。
- 手机当前 HTTPS 后端、mobile poll/ack、relay signal-only 设计不重写。

## 范围 A：抽出单角色 Owner Turn application service

- 将 `run_owner_chat_turn()` 中与 FastAPI 路由无关的编排抽到明确的 core/application service；路由层只做
  鉴权、请求校验、Dream Guard、caller profile 解析和 HTTP 错误映射。
- 服务继续复用唯一 `pipeline_registry` 实例、现有 per-owner `conversation_lock`、turn-level Reality
  scope freeze 和 `record_assistant_turn()`；不得创建第二个 Pipeline、第二把平行会话锁或直接 LLM 路径。
- 保持桌面与手机当前语义：
  - desktop provenance/live origin、WS stream/canonical replacement、desktop origin exclusion 不变；
  - mobile provenance/live origin、无 desktop stream、durable mobile mirror 不变；
  - probe 的 `trusted_user_text` 仍只取媒体拼接前用户原文；
  - `reply_to`、Dream Guard、web/coplay echo、记忆 scrub 和 slow post-process 不变。
- application service 接受内部 `TurnCallerContext`（或等价结构），至少固定：caller kind、token label/profile、
  provenance channel、live origin、durable mirror、允许的工具能力 profile。调用方不能通过 JSON body 伪造
  `uid`、`char_id`、channel、origin 或工具类别。
- 工具循环是否启用继续由现有 tool-loop/preset/角色卡合同决定；“API 可调用”不得伪装成“所有工具必然
  可用”。

## 范围 B：稳定、幂等的单角色 Turn API

新增版本化 owner-turn API（建议 `POST /v1/owner/turns`），供后续硬件麦克风、脚本或其他可信 owner
输入适配器使用。

### 请求合同

至少包含：

- `client_turn_id`：调用方生成的稳定 UUID/opaque ID，必填；
- `message`：用户真实表达，非空并有明确长度上限；
- `reply_to`：复用现有可选引用结构；
- `upload_ids`：若本轮引用已上传媒体，只接受后端签发且属于当前 owner 的 opaque ID，不接受本机路径。

明确禁止 body 提交 `uid`、`char_id`、`source`、`trust`、`tool_categories`、`origin`、任意文件路径、
token 或服务器配置覆盖。

### Caller 与权限

- API 使用 `chat` scope，但不得默认复用 `device`（仅 `ws.device`）token；承载 owner 语音输入的硬件需
  单独签发 owner-input/integration token。
- caller capability profile 由服务端 token/profile 映射：默认 integration profile 不暴露
  `desktop`、`system`、`phone_control`、`hardware` 类工具；需要额外能力时由本地配置显式放行，不能由
  prompt 或请求参数升级。
- desktop/mobile 旧入口保持现有能力面，不能因 integration profile 收窄而回归。
- 普通传感器事实、触摸、距离、光照、设备状态不允许调用本 API 冒充 owner message；继续走
  `/sensor/*`、`/watch/event`、`/ws/device` 或现有 stimulus/autonomy 边界。

### 幂等与重试

- `(caller identity, client_turn_id)` 是持久幂等键；相同键、相同规范化请求只能产生一次工具执行、一次
  LLM final、一次 memory write 和一个 canonical `turn_id`。
- 同键不同 payload 返回固定 409 conflict，不执行第二轮。
- 并发重复请求只能有一个 owner；其余等待/查询同一 in-flight 结果，不得绕过 conversation gate。
- 服务重启后重复请求仍不能重放副作用。幂等 receipt 只记录 caller、请求 hash、状态、canonical turn_id、
  时间和安全错误码，不重复保存用户正文、assistant reply、Prompt 或工具结果。
- 成功重复请求从 canonical turn/history 投影恢复同一响应；若 canonical 内容已按 retention 清理，返回
  明确的 `completed_result_expired`，绝不重新跑 LLM/工具。
- receipt 使用 `core/sandbox.get_paths()` / `DataPaths`、原子写和有界 retention；提供只读脱敏观测端点，
  不能只落盘不可观测。

### 同步与异步形态

- 保留一次 HTTP 等待完整结果的同步能力，兼容现有客户端体验。
- 为隧道/硬件提供 `202 accepted + client_turn_id/canonical turn status` 的异步模式或等价查询端点，避免
  120 秒 LLM/tool loop 被代理超时误判失败。
- 查询响应只返回当前 caller 自己的 turn；不得成为跨 token 的聊天历史读取旁路。
- 最终回复仍经正常 `turn_sink` fanout；API 不是绕过通道层的第二出口。

## 范围 C：服务器部署模式与本机能力闸门

新增明确部署模式（建议 `deployment.mode: local | remote_server`，默认 `local` 保持兼容）。该值由本地
配置决定，LLM/self-management/客户端请求均不可修改。同步更新 `docs/feature-control-surface.md`。

### remote_server 下必须 fail-closed 的能力

- `device_shutdown`、`device_sleep`：不得关闭/休眠服务器；从 schema/probe/tool loop 暴露面移除，直接
  `execute()` 也返回固定不可用结果。
- `exit_yandere` 旧 `emerald_desktop.path/...signal` 写入：不得写服务器绝对路径；remote_server 下禁用。
- `fs_list`、`fs_read`：不得把服务器仓库/挂载目录当成用户电脑供模型浏览；remote_server 下默认禁用。
- desktop action 的 `agent_actions.json` / `channel_queue.json` **本地文件 fallback**：远程模式下不得把写到
  服务器的文件宣称为已送达用户电脑。action 只有 WS ack 成功才算成功；WS 离线/ack 失败返回固定
  `client_offline`/`ack_failed`，不落服务器文件假兜底。
- 任何新发现的后端 OS command、后端 GUI、后端绝对路径或 loopback 用户设备调用，先加入同一集中能力
  表并 fail-closed，不能散落 `if remote_server`。

### remote_server 下保留的桌面/手机能力

- `desktop_minimize`、`desktop_open_url`、`desktop_play_pause`、`desktop_notify`、`play_song`、
  `toy_invite`、`dream_invite`：这些是 WS action，由 Tauri 前端执行；只要 `/ws/desktop` 在线且 ack，继续
  可用。
- `peek_screen_content`：只读取客户端已上传且通过隐私过滤的 realtime snapshot，不直接读服务器屏幕，
  保留现有 gating。
- `phone_control_start`：仍走现有手机控制合同，不把服务器当手机；是否可用按手机在线与现有权限判定。
- memory/info/web/reminder/garden、后端自有 toybox 文本和其他明确属于服务端状态的能力不因 remote_server
  自动关闭。
- `/ws/device` 是远程设备通道而非服务器本机操作，可继续连接；普通 device token 仍不获得 chat scope。

### 冻结与排除项

- `toy_vibrate`、`toy_stop`、`toy_pattern`、`toy_job_status` 及 Intiface/Buttplug runtime 不做重构；部署
  preflight 仅验证现有总开关与 opt-in 处于关闭状态。
- TTS、reference audio、GSV loopback 不纳入 readiness 判定。
- NapCat 与后端同机是部署前提；不把 `qq.host=127.0.0.1` 判成错误。

### 观测与管理面

- 新增只读 deployment-capability 投影（`state.read`）：返回 deployment mode、能力 logical name、
  `enabled|disabled|online_required|frozen`、安全 reason、最近 WS ack 时间；不返回绝对路径、端口扫描结果、
  token、URL credential 或用户正文。
- 系统状态页只显示摘要与阻塞项；配置仍通过现有受保护设置面完成。不得把“配置为远程模式”等同于
  “真实隧道已可用”。
- 对 remote_server 下被拒绝的本机能力写低敏审计计数/固定 reason；不记录工具参数中的路径、URL 正文或
  prompt。

## 范围 D：Obsidian 用户日记本地采集与服务器镜像

### 数据边界

- Obsidian 用户日记与客户端侧栏展示的“角色 inner diary”是两种数据；现有 `/diary/list`、
  `/diary/{date}` 角色日记展示合同不改名、不复用为用户日记同步。
- 原始 Obsidian vault 仍由用户电脑拥有；后端只保存供 `read_diary/search_diary/diary_reminder` 使用的
  私有镜像。
- 镜像建议位于 `data/runtime/integrations/diary/{owner}/`（最终路径须登记 `DataPaths` / data registry），
  不进入 tracked `userdata/`，不返回/持久化客户端绝对路径。
- 首版只接受现有日期文件合同 `YYYY-MM-DD.md`，允许目录嵌套；不把整个 vault 的其他笔记、附件、图片、
  插件目录或隐藏目录上传。

### 桌面采集器

- Tauri 原生侧让用户显式选择目录并把本地路径只保存在 untracked client-local 配置；WebView/后端响应/
  日志不出现完整绝对路径。
- 启动、恢复连接、用户手动“立即同步”和有界周期扫描时计算 manifest/hash，只上传新增或变化条目；不得
  每轮聊天上传全文。
- 首版可使用有界周期扫描，不强制引入 OS watcher 依赖；大目录扫描必须只匹配日期 Markdown 并设文件数/
  单文件/批次上限。
- 本地文件读取失败、编码异常、文件变化竞态单条 fail-open 并可重试，不阻断桌面聊天与 WS。
- 删除只对服务器镜像写 tombstone/soft-delete；永不删除、移动或改写电脑上的 Obsidian 文件。目录切换
  不得立即把旧镜像物理清空，需明确确认/代际切换合同。

### 同步 API

- 新增独立 `diary.sync` scope，并加入 desktop profile；mobile/device/watch/sensor profile 默认不含。
- `POST /integrations/diary/sync`（或等价版本化路径）接受 bounded batch：entry logical date、content、
  sha256、mtime/revision、deleted tombstone、client sync generation；不接受客户端绝对路径。
- 相同 hash/revision 幂等；乱序旧 revision 不覆盖新内容；同 date 冲突返回可解释状态，不静默 last-write-wins。
- `GET /integrations/diary/sync/status` 返回最后成功时间、active generation、entry/changed/tombstone/error
  计数与固定错误码，不返回正文或路径。
- 服务端原子写 manifest/entry；每批有总大小、条目数、单条大小限制。Markdown 作为不可信 authored text，
  只经既有 diary ToolResult/prompt framing 进入模型，不能携带工具授权或系统指令。

### 读取切换与兼容

- `read_diary/search_diary/has_any_diary_entry/diary_reminder` 在 remote_server 模式读取服务器镜像；不得
  回退到无效的客户端 Windows 路径。
- local 模式继续兼容现有 `diary.obsidian_path` 与 `diary_fallback/`，不强制已有本地用户迁移。
- remote_server 模式若镜像从未同步，返回明确“尚未同步/客户端离线”能力状态；不能把它误判成“用户昨天
  没写日记”并触发提醒。
- 工具已读指纹、`mark_diary_shared()`、source isolation 与记忆固化边界保持现有语义。

## 范围 E：远程地址、代理与部署前检

- `admin.host`：若隧道 agent 与后端同机并转发 loopback，可继续监听 `127.0.0.1`；只有直接监听私网卡时
  才改 bind address。不得默认裸监听公网。
- 公网入口只接受 HTTPS/WSS；反向代理必须透传 WebSocket Upgrade 与 `Authorization` header，WS idle
  timeout 大于现有 heartbeat 失活窗口。
- 桌面 Rust HTTP 当前 `.no_proxy()`：Tailscale/私网/普通直连隧道保持；若目标环境明确要求企业代理，
  另做“仅 loopback/private 绕过、remote 按显式配置”的独立改动，不在本 Brief 猜测系统代理。
- 后端 LLM/web/embedding 的代理继续只读服务器配置；任何 `proxy.*=127.0.0.1` 都解释为服务器本机代理。
- MCP 保持现有 loopback 直连、remote `use_proxy` 显式 opt-in 规则；本 Brief 不改 MCP transport。
- scoped token：desktop/mobile/device/owner-input 分开；公网客户端不使用 legacy admin secret。边缘设备不能
  因接入 Turn API 自动获得 admin/hardware/persona 权限。
- 提供只读部署 preflight，检查 bind 模式、TLS/WSS 外部声明、token profile、持久目录可写、backup
  freshness、remote_server 禁用能力、WS 最近连接与 diary sync 状态；不得主动端口扫描或回显密钥。

## 文档漂移修正

- `docs/channels.md` 曾同时存在“`/mobile/chat` 已删除”和后文“手机使用 `/mobile/chat`”的矛盾描述；已以
  当前后端 `admin/routers/mobile.py` 和 Flutter `BackendClient.sendChat()` 为真值，修正 current 文档并将旧结论标为 stale。
- 更新 `ARCHITECTURE.md`、`docs/channels.md`、`docs/tools.md`、`docs/security.md`、
  `docs/runtime-lifecycle.md`、`docs/data-taxonomy.md`、`docs/feature-control-surface.md`。
- 桌面更新 `docs/backend-integration.md`、`docs/design-constraints.md`；手机只在真实代码/合同需要时更新，
  不因本 Brief 强制改 Dart。

## 不在范围内

- 不把多角色 Stage、Dream chat 或 scheduler trigger 合并进 owner-turn API。
- 不让传感器事件直接获得用户消息的 memory/write 权限。
- 不允许客户端选择任意角色 memory scope、工具类别或调用 origin。
- 不创建公共匿名聊天、账号系统、多租户或社区插件平台。
- 不把 Obsidian vault 做成通用远程文件浏览器，不同步非日期笔记和附件。
- 不把同步成功等同于用户已授权所有日记进入长期记忆；现有工具触发与来源隔离规则不变。
- 不处理 Intiface/Buttplug、TTS、NapCat 迁移。
- 不修改现有 desktop v0.1 WS action 消息全集。

## 预计主要文件

后端：

- `admin/routers/chat.py`
- `admin/routers/mobile.py`
- 新 owner-turn application service / receipt store
- 新 owner-turn 与 diary integration router
- `core/pipeline.py`、`core/turn_sink.py`、`core/conversation_gate.py`（优先只复用，必要时薄接线）
- `core/tool_dispatcher.py`
- `channels/desktop.py` / `channels/desktop_ws.py`
- `core/tools/diary_reader.py`、`diary_tool.py`、`diary_search.py`
- `core/data_paths.py`、`core/data_registry.py`、`admin/scopes.py`
- deployment capability/preflight 投影及 admin 只读摘要
- 上述架构、安全、通道、工具、数据与控制面文档

桌面：

- `src-tauri/src/client_config.rs`
- 新 diary sync 原生模块与 Tauri commands
- `src-tauri/src/lib.rs`
- 用户日记同步设置 UI（放在连接/隐私相关设置，不混入角色 inner diary 展示）
- `src/shared/api/backend.ts` / 对应类型与 focused tests
- backend integration/design constraints 文档

手机：

- 默认无代码改动；只做当前 `/mobile/chat`、HTTPS、poll/ack 兼容验证。

## 验收标准

1. `/desktop/chat` 与 `/mobile/chat` 在抽取 service 后保持现有 reply、turn_id、memory、tool、fanout、stream
   和 durable mirror 行为。
2. 新 owner-turn API 的正常请求走同一 Reality chain；不创建第二 Pipeline/锁/记忆 writer。
3. 相同 caller + `client_turn_id` 的串行、并发和重启后重试最多执行一次工具/LLM/记忆写入，并返回同一
   canonical turn；同 key 不同 payload 固定 409。
4. integration token 不能伪造 uid/char/channel/tool capability；普通 device token 不能调用聊天 API。
5. remote_server 下 `device_shutdown/device_sleep/exit_yandere/fs_list/fs_read` schema 不可见且直接执行
   fail-closed；不会操作服务器 OS/文件。
6. remote_server 下 desktop WS 在线时 open URL、通知、最小化、媒体键和邀请 action 仍由真实 Tauri
   执行并 ack；WS 离线时不写服务器文件伪装成功。
7. Obsidian 首次同步只上传日期 Markdown；增量扫描只传变化内容，重复批次幂等，旧 revision 不覆盖新值，
   删除只产生服务器镜像 tombstone。
8. 电脑同步后退出桌面客户端，手机仍能通过一次真实聊天调用 `read_diary/search_diary` 读取服务器镜像；
   从未同步时不会误触“昨天没写”提醒。
9. 后端、桌面日志/API/观测中不出现完整 Obsidian 路径、token、日记正文、Prompt 或工具原始结果。
10. HTTPS/WSS 隧道下桌面聊天、WS action、手机聊天、mobile poll/ack、服务重启恢复均通过真实 E2E。
11. Intiface/Buttplug 保持冻结关闭；TTS 不作为失败项；NapCat 同机 QQ 通路单独 smoke，不扩展本 Brief。
12. deployment capability/preflight 能解释 disabled/online-required/frozen 状态，但不把静态配置当成真实链路
    成功。

## 验证

- 后端 focused `pytest -n auto`：旧 desktop/mobile route parity、caller profile、Dream Guard、scope freeze、
  idempotency serial/concurrent/restart/conflict、receipt retention、remote capability matrix、desktop WS ack/no-fallback、
  diary batch/revision/tombstone/limits/status、never-synced reminder。
- 工具回归：Path A probe、Path C loop、tool schema exposure、direct `execute()` fail-closed、memory/tool-read-log。
- 桌面：Vitest/TypeScript focused tests；Rust unit tests覆盖目录选择结果、路径不出站、manifest/hash、批次上限、
  reconnect/manual/periodic sync；`cargo test`、`npx.cmd tsc --noEmit`、`npm.cmd run build`。
- 手机：focused Flutter backend request/poll tests、`flutter analyze`；无 Dart 改动时不扩大到 APK/release。
- 真实隔离数据 E2E：部署临时 HTTPS/WSS 入口，使用新 scoped tokens，完成 desktop + mobile + diary + duplicate
  retry + restart + WS action ack。不得使用真实用户 vault；fixture 只含合成日期日记。
- 真实服务器 preflight：确认持久卷/备份、时区、WS idle timeout、NapCat loopback；不验证 TTS/Intiface。
- 三仓 `git diff --check`，不得夹带现有 Dream/UI/移动打包并行改动。
- 未完成真实隧道、真实 WS action ack、重启幂等和桌面关闭后手机日记读取时，整单只能标记 `partial`。

## 建议施工顺序与提交边界

1. 后端抽 owner-turn application service，旧 desktop/mobile parity 测试，独立 commit。
2. 新版本化 API、caller profile、持久幂等 receipt 与观测，独立 commit。
3. deployment mode、本机能力集中闸门、WS-only desktop action 与 preflight，独立 commit。
4. 后端 diary mirror/sync API/读取切换/安全与数据文档，独立 commit。
5. 桌面 Obsidian 目录选择、增量同步、设置/状态/i18n，独立 desktop commit。
6. 三端文档漂移、真实隧道 E2E 与仅必要修正；验收证据独立记录，不把未完成项写成通过。
