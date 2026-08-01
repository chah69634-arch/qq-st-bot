# Desktop client protocol

PresenceKit-desktop 与本后端当前正式使用的桌面协议是 **v0.1（legacy 冻结版）**。
MCP is backend-only and is not part of the desktop/mobile client transport contract.

协议正文的唯一权威位于 PresenceKit-desktop 仓库：

```text
docs/protocol-v0.md
```

ChatPanel 的 HTTP/WS 回复对账契约位于同一仓库：

```text
docs/chat-correlation.md
```

后端实现锚点：

- `channels/desktop_ws.py`：WS 帧、ack 等待与心跳（20 秒 ping，超过 70 秒无 pong 断开）。
- `admin/admin_server.py`：`/ws/desktop` Bearer header 鉴权。
- `admin/routers/chat.py`：正式发送路径 `POST /desktop/chat`。

本仓不复制协议正文，避免客户端与后端各维护一份而发生漂移。修改桌面消息类型、字段、ack 语义或 action allowlist 前，必须先在双方工单中明确升级范围；v0.1 不允许任一端单边扩展。

Tool Ephemeral Status P0 已作为配对的后端与 PresenceKit-desktop 改动交付：`tool_status` 是
S→C、无 ack、无持久 fallback 的瞬态帧，仅覆盖桌面“动向”NOW 区域，不产生聊天气泡或历史。
字段与 TTL 语义以客户端仓的 `docs/protocol-v0.md` 为准；旧客户端可忽略未知类型，但后端不得向
移动端或文件队列投递该事件。
