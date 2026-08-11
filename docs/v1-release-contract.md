# v1 发布契约

> 状态：v0.2.2 发布前基线。本文定义产品 v1 的发布边界，不是新的 wire protocol 或 architecture plan。若代码与正文冲突，以代码为准；证据锚点使用反引号标记。

## 命名与契约规则

- 产品 **v1** 是发布列车名称。桌面 wire contract 仍是冻结的 **v0.1** 协议，位于 `PresenceKit-desktop/docs/protocol-v0.md`，使用 `POST /desktop/chat` 加 `/ws/desktop`（`admin/routers/chat.py`、`admin/admin_server.py`）。本文没有暗示或随包发布 v1 WebSocket、EventBus、EventEnvelope dispatcher 或 capability negotiation。
- 当前 Flutter 前台聊天调用 `/mobile/chat`（`PresenceKit-mobile/lib/services/backend_client.dart::sendChat`），桌面前台聊天调用 `/desktop/chat`。两者共用 owner-chat pipeline；`/mobile/*` 还负责 activation、poll、ack 和 proactive delivery（`admin/routers/mobile.py`）。
- 后端拥有持久化业务事实。桌面端和移动端只拥有 presentation、本地 transport/configuration state 以及可恢复的 delivery cursor。

## 稳定 / v1 保证

| Surface | Clients | Data ownership | Failure degradation | Blocks v1 |
|---|---|---|---|---|
| Owner chat 与 memory pipeline | Desktop + mobile 前台；QQ 可选 | Backend `DataPaths`；客户端不拥有 memory | 请求错误显示出来；没有客户端 memory 替代品 | 是 |
| 桌面冻结 v0.1 contract | Desktop | 后端拥有 message/action truth；桌面端负责渲染和 ack | HTTP reply 与 WS delivery 通过 `msg_id` 去重；WS 会重连 | 是 |
| Mobile proactive queue | Mobile | 后端拥有 durable queue、id/seq；移动端保存 ack/seen cursor | Poll 可恢复错过的 signal delivery | 是 |
| Scoped bearer auth | Desktop + mobile + admin | Backend token registry | 401/403 fail closed；客户端不会静默降低 scope | 是 |
| Authored asset canonical root | Backend/admin，客户端消费 | `userdata/characters/cards/` 与 `userdata/characters/...`；只允许 legacy read | 迁移期间对旧 `characters/` 提供 read fallback | 是 |
| Atomic file writes 与 compatibility reads | Backend | 仅后端 | 在已实现的范围内保留旧数据并使用 read fallback | 是 |

## 已支持但可选

| Surface | Clients | Data ownership | Failure degradation | Blocks v1 |
|---|---|---|---|---|
| Desktop WS proactive/action delivery | Desktop | 后端拥有 queue/turn truth | 现有 HTTP/chat 路径和桌面 fallback 仍可用 | v0.1 contract 测试通过后不阻塞 |
| Mobile relay wake signal | Android mobile | 后端 poll queue 拥有 body；relay 只有 signal | signal 失败/重连时回退到 poll/AlarmManager recovery | 基线聊天不阻塞；若声称可靠后台 delivery 则阻塞 |
| Tool loop（Path C） | Backend；桌面/移动设置可配置 | 后端 registry/config/character permission | 全局默认关闭；非 loop turn 仍使用 Path A probe | 否 |
| QQ、TTS、stickers、sensors | 对应可选 channel/client | 后端 truth；客户端只采集/渲染 | 功能可缺失，或本地 UI 报告失败 | 否 |

## 实验性

| Surface | Clients | Data ownership | Failure degradation | Blocks v1 |
|---|---|---|---|---|
| Android relay 在 OEM/Doze/reboot 下的持久性 | Android | 后端 queue + 移动端本地 cursor | Poll compensation 只能在 TTL/eviction 前恢复 | 普通前台使用不阻塞；在有真机证据前不得宣传为保证能力 |
| MCP 外部工具（可选后端扩展） | 默认 Path C；仅显式暴露时共享 Path A | 外部 server 拥有工具数据；后端按条件暴露工具 | 未配置、关闭或失败的 MCP 不会改变 Chat、Memory、Scheduler、Dream 的既有路径；工具失败不能阻塞普通聊天 | 否 |
| Dream Stage、Live2D/3D、hardware、Garden、Activity | 对应客户端 | 后端 domain data；客户端负责渲染/控制 | feature-local error/empty state；没有跨 domain fallback | 否 |

MCP 仍是 **Experimental**，不是稳定或“已支持但可选”的 v1 surface。可选的含义是后端可以不配置任何 server 运行；它不会扩大 v1 发布契约。启用后，MCP 仍受 path-specific owner-turn gate、工具暴露和角色边界、server/tool allowlist、`exclude_tools`、timeout/cancellation、不受信任结果的有界 framing，以及 API-call/action observability 约束。`hardware_gateway` 是外部 MCP Server 实现；MCP 和该 gateway 都不阻塞 v1.0。

## 延后到 post-v1

| Item | 延后原因 | v1 规则 |
|---|---|---|
| 新的桌面 WebSocket 协议（`user_message`、`assistant_message`、envelope/capability） | 双方目前只实现 v0.1 | 不实现，也不宣传为 v1 |
| 统一 EventBus/EventEnvelope dispatcher | 现有入口有意保留各自 gate | 不新增 dispatcher，也不 retrofitting 既有流程 |
| Android Keystore-backed token migration | 已实现：`BackendSecurityPolicy` 使用 `CredentialMigration` 和 `AndroidKeystoreCredentialStore`；legacy 明文只在 secure write 成功后清除 | 真机升级/恢复验证和无明文残留验收仍是发布证据 |
| 扩大 Live2D、3D、MCP、hardware、Garden、Activity 范围 | 没有发布关键证据或跨仓契约 | 冻结 feature scope |

## 本次发布前检查修正的文档漂移

1. Backend README 的 card 位置和 memory tool-loop 状态。
2. Desktop architecture 中旧 event-log/diary 路径，以及把未来 WS 提案与产品 v1 混为一谈的问题。
3. Interaction envelope 文档中过时的 v0.2+ 承诺；现在已明确标为历史/延后。
4. Release guide 中关于 mobile 没有 CI 的错误说法，以及把 debug-signed APK 当作可发布产物的问题。
5. Mobile channel 文档现在把 `/mobile/chat` 命名为实际 Flutter 前台聊天 endpoint。
