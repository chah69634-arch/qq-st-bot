# Brief 194：管理面板原生 no-proxy 直连入口

## 状态

`ready` / cross-repo implementation

## 背景与结论

远程单机部署中，PresenceKit Backend 监听服务器 `127.0.0.1`，由 Tailscale Serve 暴露 tailnet-only hostname。桌面客户端的 Rust `reqwest` 请求已经统一使用 `.no_proxy()`，WebSocket 也显式绕过系统代理；但管理面板由普通系统浏览器加载，首次 HTTP 请求是否经过代理由浏览器/PAC 决定。

后端无法在请求尚未到达时要求浏览器绕过代理，因此该问题不能只改 PresenceKit Backend 解决。可行方案是在 PresenceKit desktop 中提供一个只绑定本机回环地址的临时反向代理：上游连接复用已验证的 backend URL，并由 Rust HTTP/WS 客户端显式 no-proxy；系统浏览器只访问本机 loopback URL。

本工单不承诺让任意外部浏览器自动绕过系统代理，也不修改用户全局代理设置。

## 开工前必读

Backend：

1. `AGENTS.md`
2. `docs/security.md`
3. `docs/security_model.md`
4. `docs/runtime-lifecycle.md`
5. `docs/three-repo-interface-catalog.md`
6. `docs/dev-environment.md`

Desktop：

1. `AGENTS.md`
2. `docs/backend-integration.md`
3. `docs/protocol-v0.md`
4. `src-tauri/src/client_config.rs`
5. `src-tauri/src/lib.rs`
6. `src-tauri/src/ws_bridge.rs`

## 目标体验

在桌面客户端的连接设置或工具菜单提供“打开管理面板”命令：

1. 校验当前 `backendBase` 是允许的 `http`/`https` URL，且与已保存连接配置完全一致。
2. 启动或复用一个仅监听 `127.0.0.1:<随机端口>` 的本地桥接服务。
3. 桥接服务使用 `.no_proxy()` 上游客户端访问配置中的 backend。
4. 使用系统浏览器打开带高熵临时 capability path 的 loopback URL。
5. 页面关闭或桌面应用退出后停止桥接；空闲超时后自动回收。

代理软件是否开启不应影响管理面板访问。现有直接访问远程 URL 的方式继续保留，供已经配置 DIRECT/PAC 的用户使用。

## 安全边界

- 只监听 IPv4/IPv6 loopback，不监听 LAN、Tailscale 或 `0.0.0.0`。
- 端口由操作系统随机分配，不使用固定公开端口。
- 根路径必须包含启动时生成的高熵 capability；无 capability、错误 Origin/Host 或非预期方法 fail closed。
- 上游 origin 只能来自当前已保存的 `backendBase`，不得接受页面 query/body/header 提供任意 URL，避免 SSRF/open proxy。
- 不把 admin token 放入 URL、命令行、日志、窗口标题或 capability。浏览器端继续使用现有 scoped-token 登录模型；桥接不得偷偷提升 scope 或注入 admin token。
- 严格剥离 hop-by-hop headers；重建 Host；限制 request/response header 和 body 大小；上传端点按现有产品上限流式转发，不整包读入内存。
- 只允许 PresenceKit 管理面所需的 HTTP methods、路径和 WebSocket upgrade。不得成为通用 TCP/HTTP proxy。
- 正确转发状态码、content type、cache、range、SSE/stream 和 WebSocket close code；不得把错误页伪装成 200。
- 日志只记录 method、脱敏 path class、status、latency 和错误类别；不记录 token、query secret、请求正文、响应正文或完整 URL。
- 桌面应用退出、backend 配置改变、显式关闭入口或空闲超时后，旧 capability 立即失效。

## 建议实现边界

Desktop 新增独立模块，例如：

```text
src-tauri/src/admin_bridge.rs
```

职责：

- 管理 bridge lifecycle、随机 loopback listener、capability 和 idle timeout；
- 复用统一 no-proxy HTTP client policy；
- 受限地转发管理面静态资源和 API；
- 若管理面当前/未来需要 WebSocket，提供显式 WS relay；
- 暴露 `open_admin_panel`、`admin_bridge_status`、`stop_admin_bridge` Tauri commands。

React 设置面只负责触发、显示“直连/已关闭/启动失败”状态和可操作错误，不自行实现浏览器代理或保存 capability。

Backend 原则上无需 runtime 改动。如果为 bridge 增加识别 header、健康检查或 CSP/connect-src 兼容，必须保持普通 tailnet/browser 路径可用，且不得降低鉴权要求。

## 三面闭环

1. Backend/admin：核对静态资源、API、鉴权、上传、流式响应和可能的 WS；bridge 不得绕过 scope。
2. Desktop：增加入口、状态、生命周期、no-proxy relay 和失败提示；连接配置改变时自动作废旧 bridge。
3. Mobile：不实现等价功能时，在接口总账标为 desktop-only；手机继续依赖 VPN 的 per-app bypass、系统 DIRECT/PAC 或可工作的系统网络路径，不虚构已解决。

## 测试

至少覆盖：

1. listener 只绑定 loopback，端口随机；错误 Host/capability/Origin 被拒绝。
2. 上游 URL 只能来自保存的 backend 配置；路径、query、fragment、scheme 边界不会形成 SSRF/open proxy。
3. 测试环境设置不可用的 `HTTP_PROXY`/`HTTPS_PROXY` 后，bridge 仍可连接 mock backend。
4. 静态 HTML/JS/CSS、JSON GET/PUT/POST、401/403/404/405、上传和 streaming 的状态/header/body 保真。
5. Authorization header 不写日志、不出现在 URL；bridge 不注入或升级 token。
6. WS handshake、双向 frame、ping/pong、关闭和 backend 断连正确；若审计确认管理面无 WS，可把 WS 标为预留并给出证据，而不是实现未使用复杂度。
7. 多次点击复用单实例；配置切换、显式停止、空闲超时和应用退出均释放端口、失效 capability。
8. 原 desktop HTTP/WS no-proxy、直接远程管理面和 backend API 最小回归不受影响。
9. Windows 实机在系统代理开启且远程 tailnet hostname 未列入 DIRECT 时，桌面入口仍能打开并完成 whoami/设置读写。

按各仓 `docs/dev-environment.md` 执行相关测试。涉及前端资源时遵守 desktop 的构建和缓存规则。

## 文档

实现后同步：

- Backend `docs/three-repo-interface-catalog.md`：标明 transport bridge 是 desktop ownership，不是新 backend 鉴权边界。
- Backend `docs/known-issues.md`：关闭或更新浏览器系统代理观察项。
- Desktop `docs/backend-integration.md`、连接设置文档和 known issues：说明 direct URL 与 native bridge 两条路径。
- Ubuntu 部署文档：把手工 DIRECT/PAC 规则保留为通用浏览器方案，把桌面 bridge 写成可选入口。

## 非目标

- 修改 Windows/macOS/Linux 全局代理或 PAC。
- 为任意浏览器扩展安装规则。
- 将管理面公开到公网。
- 在 backend 中硬编码某个 tailnet hostname。
- 创建会转发任意目标的通用代理。
- 让手机端自动继承桌面 bridge。

## 验收

- 系统代理开启且不放行远程 tailnet hostname时，桌面“打开管理面板”可用。
- bridge 仅 loopback 可达，未知本地进程没有 capability 时无法使用。
- 现有 scoped token、安全 header、API/WS 行为和错误语义不变。
- 关闭桌面应用后 listener 消失，旧 URL 不可复用。
- 跨仓接口总账、已知问题、设置 UI 和最小回归测试完成闭环。
