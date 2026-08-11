# Brief 174：桌面 WebView 生命周期、资源分包与内存优化

## 背景与目标

一次 Windows debug 运行时简单快照显示，Tauri 主进程及其 WebView2 进程合计约 1.2 GB working set、约
788 MB private memory；npm/Node/Cargo 等开发进程还会额外占用内存。debug 数据不能替代 release 验收，且 working set
会包含共享页，但 private memory 和 renderer 数量仍说明桌面端存在明确优化空间。

当前主要结构性原因：

- `tauri.conf.json` 启动即声明 main、pet、presence-nag 三个窗口；隐藏窗口仍会创建 WebView2 renderer；
- 所有窗口共用 `src/main.tsx`，并静态导入 Chat、Pet、PresenceNag、Activity、Toy、Room、DiaryDetail 等模块；卫星窗口会
  加载不属于自己的前端运行时和依赖；
- 主 ChatWindow 在 Activity/Toy/Room 等覆盖层出现时仍保持挂载，其动画、轮询和资源可能继续运行；
- Live2D/WebGL/particle/audio/observer/timer 等资源虽然已有部分 cleanup，但缺少统一的真实窗口生命周期与重复开关基线；
- Obsidian 扫描会先把最多 2000 个日期 Markdown 内容装进 `BTreeMap` 再筛选变化，极端情况下存在较大临时峰值，尽管本次
  快照中 Rust 主进程并非主要占用者。

本 Brief 目标是减少不必要的 renderer、拆分卫星窗口资源、暂停不可见重型工作，并建立 release 可复现内存证据。优化不能
破坏桌宠唤起、Presence Nag、聊天连接、Dream/Room、日记同步和跨窗口音频合同。

## 已决定的边界

1. 先测 release 基线，再以同机、同配置、同场景做前后对照；不把 debug 数字直接写成正式上限。
2. 优先消除“不需要却常驻”的 WebView，而不是先做微小 JS 对象优化。
3. `presence-nag` 按需创建、使用完成后销毁；不得仅 hide 后永久常驻。
4. `pet` 生命周期由桌宠功能状态决定：未启用时不创建；启用后可为响应速度保留，明确关闭/禁用时销毁。
5. main chat 的网络连接、消息 store 和 canonical replacement 不能因为覆盖层隐藏而丢失；优先暂停视觉/轮询资源，不贸然
   卸载仍承担协议状态的 controller。
6. 不通过禁用核心功能、降低对话质量或移除 Live2D/Room 来伪造低内存。
7. 不修改后端 owner-turn、记忆、工具或协议语义；跨仓只做现有窗口/接口所需兼容验证。
8. 不承诺一个跨机器绝对 MB 上限；硬验收以窗口/renderer 生命周期和无界增长消除为主，内存以同机相对变化记录。

## 范围 A：建立可复现的 release 内存基线

新增桌面运行时内存验收文档或脚本，记录：

- desktop commit SHA、构建类型、Windows/WebView2/Tauri 版本、GPU 模式和后端连接状态；
- 根 Tauri PID、全部 WebView2 子进程 PID、process role、working set、private bytes；
- npm/Node/Cargo 等开发工具进程与正式应用树分开统计；
- 冷启动后 30 秒、静置 10 分钟、打开/关闭 Pet、Presence Nag、Room、Dream、Diary Detail 前后；
- 每个重型窗口连续开关 10 次后的峰值、回落值、renderer 数量和是否单调增长；
- 后端离线、恢复连接和窗口 visibility 变化场景。

PowerShell/脚本只读采样进程树，不结束用户其他进程，不依赖模糊进程名把无关 Edge 实例算入。原始数据不得包含 token、URL
credential、聊天正文或本机用户目录。

正式结论分为：

- `debug-observation`：仅用于定位；
- `release-baseline`：同一 release 构建的优化前数据；
- `release-after`：同机同配置优化后数据；
- `real-window-e2e`：真实窗口创建/销毁和资源回落证据。

## 范围 B：Presence Nag 与 Pet 按需窗口生命周期

### Presence Nag

- 从 `tauri.conf.json` 移除启动即创建的 hidden `presence-nag`，改为收到真实显示请求时按需创建。
- 创建逻辑必须并发幂等：同一时刻多个请求只产生一个 label；已存在则 focus/show/update，不重复开 renderer。
- 关闭、完成、超时或取消后销毁 WebView/window，而不是只 hide；销毁失败可观测但不阻断主聊天。
- action/IPC 发送前正确处理“窗口尚不存在”，不能继续假设 config 已预建。
- 重建后事件监听只绑定一次，不因多次开关累积 callback。

### Pet

- 桌宠设置未启用、首次配置尚未完成或用户明确关闭时，不创建 pet WebView。
- 启用/首次唤起时按需创建；hide/show 的保留策略写入生命周期文档。
- 用户关闭“桌宠功能”或退出应用时真正销毁 pet WebView、Live2D/Canvas/audio/observer/timer 资源。
- pet window 恢复时保持位置、点击穿透、置顶、透明窗口和多屏边界现有合同；不得为省内存回归桌宠体验。
- 主窗口与 pet 的跨窗口音频/事件初始化必须按窗口角色最小化，不能让 pet 加载完整 Chat/Dream/Room 控制器。

### Diary Detail 与其他动态窗口

- 审计 Diary Detail、Dream 辅助窗口和未来动态窗口：close 是否真实 destroy、再次打开是否单实例、监听是否解绑。
- 建立统一 window factory/registry 仅在现有结构可薄复用时使用；不得为“统一”重写全部 Tauri 窗口协议。

## 范围 C：按窗口角色分包与最小化 bootstrap

重构 `src/main.tsx` 或 Vite entry：

- 入口先只解析 `windowView`/window label，再动态 import 对应窗口模块；
- main 只加载 Chat/Activity/Toy/Room/Dream 所需 bundle；
- pet 只加载 Pet、Live2D 与其必要 store；
- presence-nag 只加载 Nag 视图和最小 IPC/i18n/theme；
- diary-detail 只加载日记详情与最小依赖；
- theme/i18n 可共享，但 UI prefs、cross-window audio、WS/chat controller 等初始化必须按窗口角色决定，不能对每个 WebView 全量
  执行。

构建后检查 Vite chunks/入口依赖：pet/nag/diary-detail bundle 不得静态包含 Chat、Dream、Room/Three.js 等无关模块。动态 import
失败必须显示可理解的本地错误并允许关闭窗口，不让透明空白 renderer 永久驻留。

## 范围 D：不可见主界面的资源暂停

为 Activity、Toy、Room、Dream 等覆盖状态和 Tauri window visibility 建立明确的 `active/visible` 信号：

- ChatWindow 被完全覆盖或主窗口隐藏时，暂停非必要粒子 RAF、装饰动画、缩略图刷新和高频轮询；
- 保留 WS、消息队列、canonical replacement、必要 heartbeat 与正在进行的发送/stream 状态；
- 恢复可见时只重启一个 RAF/timer/listener，不因 React StrictMode effect 双执行重复绑定；
- Room/WebGL close 必须 cancel RAF、dispose renderer/texture/material、移除 observer/listener，并在可行时释放 context；
- audio node、MediaStream、Object URL、ResizeObserver、MutationObserver、setInterval/setTimeout 建立 owner 和 cleanup；
- Pet/Nag/Diary Detail 销毁后不得继续接收全局事件或持有大 store snapshot。

不要以“覆盖时卸载整个 ChatWindow”为默认方案；若确需卸载，必须先把协议状态迁移到窗口级 controller/store，并证明消息、
stream、重连和草稿不丢。

## 范围 E：Obsidian 扫描临时内存优化

这是次优先级，只有在窗口/分包完成后实施：

- 扫描阶段先读取 metadata 并流式计算 hash；与 manifest 相同的文件不长期保留全文。
- 只为本批需要上传的 changed entries 读取/保留完整 Markdown，继续遵守单文件、批次数和 batch bytes 上限。
- 文件在 hash 与读取间变化时单条重试或下轮处理，不能上传 hash/content 不一致组合。
- 保持只匹配 `YYYY-MM-DD.md`、路径不出站、原文件只读、单条 fail-open 和 tombstone/generation 合同。
- 不为了省内存引入全 vault watcher 或把文件读取搬进 WebView。

## 范围 F：运行时观测与诊断

- 开发诊断可显示当前窗口 label、created/visible 状态、最近创建/销毁时间和 renderer 角色；不记录标题正文或 URL credential。
- 如果新增持久 trace/台账，必须同时提供只读观测入口并走有界 retention；若仅是当前进程内诊断，可保持非持久聚合。
- 正式 release 默认不持续高频采样进程内存；采样由显式诊断或验收脚本触发。
- 管理面/桌面“内存优化已启用”不得替代真实 release 前后测量。

## 不在范围内

- 不修改后端聊天、owner-turn API、记忆、工具权限、MCP 或日记镜像协议。
- 不删除 Pet、Presence Nag、Room、Dream、Diary Detail 等产品功能。
- 不用降低模型 context、清空用户缓存、删除真实数据或缩短记忆 retention 来降低桌面 RAM。
- 不把 OS WebView2 共享进程、GPU cache 或开发工具进程误判成 Tauri 私有泄漏后执行破坏性清理。
- 不以关闭 GPU、禁用硬件加速作为默认优化；只有真实兼容问题才另开平台 Brief。
- 不做无证据的全局 timer 重写；先定位 owner、生命周期和真实增长曲线。
- 不处理后端服务器内存、NapCat、Intiface/Buttplug 或 TTS。

## 预计主要文件

桌面仓：

- `src-tauri/tauri.conf.json`
- `src-tauri/src/lib.rs`
- 当前 window/action 创建与 Presence Nag 调度相关 Rust 模块
- Pet window 创建/设置接线相关 Rust/TypeScript 模块
- `src/main.tsx`
- 新的按窗口角色 bootstrap/entry 模块
- `src/windows/pet/`
- `src/windows/presence-nag/`
- `src/windows/chat/` 及真实 overlay/visibility owner
- Room/particle/audio 资源 owner 与 cleanup hooks
- `src-tauri/src/diary_sync.rs`（仅范围 E）
- focused frontend/Rust tests
- 桌面 backend integration/design constraints/runtime 文档
- 新的 release memory baseline/验收记录模板或只读采样脚本

后端仓默认只保存本 Brief 工单，不修改业务代码。若桌面需要协议字段变化，必须先证明现有 Tauri 内部合同无法承载并另开窄
范围协议 Brief。

## 验收标准

1. release 冷启动且 Pet 未启用时，不创建 pet WebView；没有 Nag 请求时，不创建 presence-nag WebView。
2. Presence Nag 首次显示能按需创建，关闭后 window label 消失；连续 10 次显示/关闭不产生递增 renderer 或重复 callback。
3. Pet 启用时可正常创建、定位、置顶、交互；功能禁用后真实销毁，重新启用可恢复且不重复绑定。
4. pet/nag/diary-detail 构建入口不静态加载 Chat/Dream/Room 等无关大模块；构建产物有可审计的 chunk 证据。
5. 主窗口隐藏或被重型覆盖层完全遮挡时，非必要 RAF/轮询暂停；WS、stream、消息 mirror 与 canonical replacement 不丢。
6. Room/Dream/Pet/Nag/Diary Detail 连续开关后，renderer 数量回到设计基线；private memory 在合理回收窗口内形成平台而非持续
   单调增长。
7. 同机同配置 release-after 相比 release-baseline 明确下降；若未达到预期，报告进程/窗口/component attribution，不把结构
   改动冒充已节省内存。
8. 日记扫描优化后，相同 manifest 的大目录不会在内存长期保存所有正文；同步 hash、revision、batch、tombstone 和路径隐私
   合同不变。
9. debug、release、真实窗口证据分层记录；不得用源码检查或 Vitest 冒充 WebView2 真实回收。
10. Windows 主目标平台完成真实运行时验收；其他平台未执行时明确 `not-run`，不默认通过。

## 建议量化指标

以下是同机同配置的验收目标，不是跨机器绝对承诺：

- Pet 关闭、Nag 未触发的 idle renderer 数量至少减少对应的两个常驻窗口 renderer；
- main-only release idle private memory 相对优化前基线目标下降 25% 以上；未达到时不强行失败，但必须解释剩余占用并决定是否
  继续拆包；
- 任一重型窗口连续 10 次开关后，回落 private memory 不应随次数近似线性增长；
- Nag 销毁、Pet 禁用后 120 秒内，相关 window label 与页面 RAF/timer/listener owner 均为零；WebView2 自身进程池是否延迟
  退出单独记录，不用进程名猜测资源仍被页面持有。

## 验证

- 前端 focused tests：window-role dynamic import、bootstrap 选择、visibility pause/resume、StrictMode 重入、timer/RAF/listener cleanup。
- Rust focused tests：单实例 window factory、并发 create、show/focus、destroy、Pet enabled/disabled、Nag action 在窗口不存在时创建。
- `npx.cmd tsc --noEmit`、相关 Vitest、`cargo test`、`npm.cmd run build`；只跑改动相关套件，构建用于检查真实 chunk。
- 真实 Windows release smoke：按范围 A 场景采样进程树，连续开关窗口并保存脱敏前后对照。
- 手工检查 Pet 透明/置顶/点击、Nag 展示/关闭、Room/Dream、Diary Detail、后端断线恢复和跨窗口音频。
- `git diff --check`；不得夹带后端 Brief 173、移动端、Dream 功能或其他并行 UI 改动。
- 未完成 release runtime 和连续开关内存测量时，只能标记 `partial`，即使单元测试和 build 通过。

## 建议施工顺序与提交边界

1. release baseline 采样脚本/记录模板和优化前证据，独立 desktop commit。
2. Presence Nag 按需创建/销毁与 focused tests，独立 desktop commit。
3. Pet feature-driven 生命周期与 focused tests，独立 desktop commit。
4. window-role 动态分包和最小 bootstrap，独立 desktop commit。
5. overlay/visibility 资源暂停与真实 cleanup 修复，独立 desktop commit。
6. Obsidian 扫描临时内存优化（确有收益时）与 Rust tests，独立 desktop commit。
7. Windows release-after 真实窗口/内存复测与文档收口，独立证据 commit。

每阶段完成相关测试、build 或真实运行时检查后立即提交。任何“内存下降”结论必须附同机同配置数据，不得只凭任务管理器单个
进程截图。
