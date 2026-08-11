# Brief 165：将梦境回放从 Chat Sidebar 迁入 DreamWindow

## 背景

Brief 164 的桌面实现把“梦境回放”错误地放进了 Reality 主聊天窗口的 Ribbon / Chat Sidebar，并新增了 `SubDreamReplay`。正确产品层级是现有 Dream 页面：入口属于 Dream Sidebar；选中历史梦后，DreamWindow 的主对话区域切换为该场梦的只读聊天回放。

本 Brief 只纠正桌面信息架构与呈现位置。后端 archive/operations API、后端管理面梦境观测、退出合同和明信片逻辑不在本 Brief 重写。

## 正确交互

- “梦境回放”入口放在现有 Dream 页面自己的 Sidebar 内。
- 入口与 Dream 页面现有侧栏项目同级，不加入 Reality Chat 的 Ribbon 或 Sidebar tab。
- Dream Sidebar 先显示历史梦列表；点击一场梦后，DreamWindow 主对话区域切换为该场 transcript。
- transcript 使用 Dream 模式现有的正常聊天视觉、气泡、排版与滚动体验。
- 回放期间 Dream Sidebar 保留列表/选中态，并提供返回当前 Dream 页面默认内容的操作。
- 不创建独立窗口，不弹出日记详情小窗，不回到 Reality Chat，不替换 Reality ChatPanel。

## 范围 A：删除错误入口

- 删除 Reality Chat Ribbon 中的“梦境回放”按钮。
- 删除 Chat `SidebarPanel` 的 `dream-replay` tab、标题元数据与分支。
- 删除或迁移 `src/windows/chat/components/SubDreamReplay.tsx`，不得在 Chat 目录留下只为 DreamWindow 服务的兼容壳。
- 清理只服务错误入口的 UIKit icon、i18n key、文档描述和测试。
- 不改动 Chat 日记、花园、状态、flow 等既有 Sidebar 行为。

## 范围 B：接入 Dream Sidebar

- 先按当前实现定位 DreamWindow、Dream layout、Dream Sidebar/tab 和主 transcript 的真实 owner；沿用现有结构，不新建第二套 Dream 页面。
- 在 Dream Sidebar 增加“梦境回放”列表视图，复用已完成的 archive list API 与分页/错误处理逻辑。
- 列表项至少显示日期、角色、模式、回合数和安全摘要；当前仍活跃、尚未 archive 的梦不显示。
- 列表选择状态由 DreamWindow 层持有，不能写入 Reality `StateEngine` 当前聊天，也不能注册 Reality WS 去重。

## 范围 C：Dream 主对话区只读回放

- 选择历史梦后，DreamWindow 主聊天区域进入 `replay` 展示模式，并读取 archive detail。
- 使用 Dream 当前用户/角色消息气泡的纯展示层；视觉、宽度、段落、时间和滚动手感应与正常 Dream 聊天一致。
- 历史消息全部静态呈现：不播放逐字动画，不触发 pseudo-stream，不触发 TTS，不订阅/消费 WS，不调用 Dream chat/enter/exit/wake/resume API。
- replay 模式隐藏或禁用输入框、发送按钮、退出/挽留等仅对活跃 Dream 有意义的操作，并显示明确的“只读回放”状态。
- 新到达的 Reality/Dream WS 消息不得追加到历史回放；退出 replay 后再按现有 Dream 状态恢复正常页面。
- 切换场次、返回列表、关闭 Dream 页面时取消/忽略过期请求，避免慢响应覆盖新选择。
- 不把 archive transcript 写回 short-term、当前 Dream log、Reality history 或任何 memory。

## 范围 D：空状态与兼容

- 无历史梦、加载失败、详情损坏、旧 archive 缺元数据、超长 transcript 均有明确状态。
- 超长梦不得一次渲染导致 DreamWindow 卡顿；沿用 API 分页或在前端做有界分批呈现。
- 角色头像/名称按 archive char_id 与当前角色资产解析；缺失资产用现有 Dream fallback，不硬编码角色名。
- 新增/调整文案完整支持中英文实时切换，不向 `legacy.ts` 追加新 key。

## 文档同步

- 修正 `ARCHITECTURE.md`、`docs/frontend-structure.md`、`docs/dream-hud.md`：回放属于 DreamWindow，不属于 Chat Sidebar。
- `docs/backend-integration.md` 保留 archive API 契约，但删除错误的 Chat Sidebar 消费描述。
- 不修改后端 `docs/dream.md` 中已经成立的 archive/operations 合同。

## 不在范围内

- 不修改后端 archive、operations、退出、afterglow、scheduler 或 postcard 业务逻辑。
- 不改后端管理面梦境观测页面的位置。
- 不增加 Reality Chat 的回放入口或快捷按钮。
- 不创建新 Tauri WebviewWindow。
- 不让回放继续梦境、发送消息、重新生成内容或触发语音。
- 不顺手重构 DreamWindow、ChatPanel 或全局布局系统。

## 预计主要文件

- 删除/回退错误接线：
  - `src/windows/chat/components/Ribbon.tsx`
  - `src/windows/chat/components/Sidebar.tsx`
  - `src/windows/chat/components/SubDreamReplay.tsx`
  - `src/windows/chat/components/UIKit.tsx`（仅当 icon 无其他消费者）
- 正确接线：
  - `src/windows/dream/` 下当前 DreamWindow、Sidebar、聊天 transcript 与 hooks
  - `src/shared/api/dream-replay.ts`
  - `src/shared/api/dream-types.ts`
  - `src/shared/i18n/locales/zh-CN.ts`
  - `src/shared/i18n/locales/en-US.ts`
- 文档与相关纯逻辑测试。

施工前必须重新阅读 `Emerald-client/AGENTS.md`、`ARCHITECTURE.md`、`docs/frontend-structure.md`、`docs/backend-integration.md`、`docs/dream-hud.md`、`docs/design-constraints.md`，以当前 DreamWindow 真实结构为准。

## 验收标准

1. Reality Chat Ribbon 与 Sidebar 不再出现“梦境回放”。
2. Dream 页面 Sidebar 能列出 archive 历史梦并选择一场。
3. 选择后，DreamWindow 主聊天区域以正常 Dream 气泡视觉显示只读 transcript。
4. 回放不弹窗、不跳 Reality Chat、不创建独立窗口。
5. replay 模式没有输入/发送/退出/挽留动作，不触发 TTS、WS、pseudo-stream 或任何 pipeline。
6. 退出 replay 后，Dream 页面恢复当前真实状态；回放消息没有污染任何当前会话。
7. 长梦、空列表、失败、快速切换、中英文和窄窗口完成目检。

## 验证

- 更新/增加纯逻辑测试，覆盖 replay view state、场次切换、过期响应忽略、静态消息映射。
- `npm test`、`npx.cmd tsc --noEmit`、`npm.cmd run build`。
- 涉及 Rust/API command 变化时运行 `cargo check`；若仅移动 React 消费层且 command 不变，不机械修改 Rust。
- Tauri/浏览器目检：Dream Sidebar 列表 → 选择长梦 → 主区域回放 → 返回 → 切换场次 → 退出回放。
- 静态检索断言 Chat Ribbon/Sidebar 不再含 `dream-replay`，DreamWindow 路径存在正向命中，防止只删不接。
- `git diff --check`，确认不夹带当前工作树中其他并行样式/活动页改动。

## 提交边界

这是一张独立纠偏 commit：删除错误 Chat 接线、迁入 DreamWindow、测试与文档一起提交。不得 amend 或重写已存在的 Brief 164 历史提交；用新 commit 保留问题和修复轨迹。
