# Brief 164：梦境聊天回放、退出闭环与明信片观测

## 背景与现场结论

单人 Dream 每场已有独立 archive JSONL，但桌面端没有面向用户的回放入口；后端管理面也没有集中展示梦境退出、Reality afterglow 主动开口和梦境明信片 schedule 的只读观测页。

近期两场长梦暴露出同一个退出契约缺口：角色在可见回复中已经明确同意回到现实并完成叙事退场，但回复缺少 Dream pipeline 当前要求的机器标记，`exit_accepted` 仍为 `false`，状态没有从 `DREAM_ACTIVE` 进入关闭流程。用户随后通过桌面退出动作调用 `POST /dream/exit`，最终只能按 `hard_exit` 归档。

这里的 `hard_exit` 仅表示“由绝对穿透的强制出口关闭”，不等于梦短、不完整、内容异常或用户负面中断。当前 postcard 用 `exit_type == hard_exit` 一刀切排除，导致“完整梦已经自然结束，但因机器标记丢失而补点退出”的场景被误杀。

本 Brief 修复机器状态闭环，增加后端管理面观测，并在桌面 Dream 侧边栏增加只读聊天式回放。

## 产品决定

- 梦境回放放在 `Emerald-client` 主聊天窗口现有 Sidebar 体系：像“日记”一样增加一个 Ribbon/侧边栏开关，并拥有一张独立的侧边页面。
- 点击一场梦后，直接在当前侧边页面内从列表切换为详情；不创建日记详情那种独立 Webview 小窗，不打开 Dream overlay，也不替换主聊天区域。
- 详情不按文章/日记正文展示，而按只读聊天记录展示用户与角色的逐回合气泡。
- 梦境运行、退出、afterglow、Reality 主动感想和明信片队列的诊断与观测全部放在 `Emerald-presence` 后端管理面板；桌面端不承载 debug 状态。
- `hard_exit` 继续保留为任何时候都可用的绝对逃生通道，不得因本 Brief 增加确认、LLM、锁或其他阻塞。
- 明信片资格按“梦是否完整、是否自然收束”判断，不能继续把所有 `hard_exit` 等同于异常梦。

## 目标

1. 角色接受退出后，机器状态可靠地完成关梦，不再出现“文字已经醒了、系统仍在梦里”。
2. 区分退出机制、退出发起方和梦境完成度，避免用一个 `exit_type` 混合三种语义。
3. Reality `dream_exit` 主动感想有明确的 pending/blocked/sent/expired 观测，并避免被普通候选长期饿死。
4. 后端管理面可查看梦境 archive、afterglow、主动感想和明信片队列状态。
5. 桌面 Dream 侧边栏可按场次浏览，并以聊天记录形式只读回放。

## 范围 A：退出语义与可靠闭环

### A1. 保留强制出口不变量

- `POST /dream/exit` 与 `/stop` 仍无条件、立即、幂等地关闭当前梦。
- 强制出口不得等待 LLM、不得依赖角色同意、不得被 non-lucid、强度、DND、调度器或客户端状态阻断。
- 不改变 `/dream/wake` 的一次性挽留合同。

### A2. 机器可读的角色接受结果

- 审计 `dream_prompt` 中退出请求协议和 `dream_pipeline.py` 对机器标记的解析。
- 角色接受退出必须产生可靠的机器可读控制结果；控制信息在写 archive、返回客户端和进入任何 prompt 前剥离。
- 不允许仅扫描可见自然语言中的“醒来、回去、退出”等词来猜测关闭，避免叙事误触。
- 不增加 send 前第二次 LLM/网络往返。若采用格式校验或本地修复，必须是有界、本地、可测试的路径。
- 当用户本轮明确请求退出且角色可见回复呈现接受、但机器控制字段缺失或非法时，记录结构化 `control_missing` 观测；不得静默伪装成正常接受。
- 施工时优先建立单一结构化控制合同，并让模型格式失败走确定性的本地降级。降级不得根据任意台词关键词关闭梦，也不得削弱用户的硬退出能力。

### A3. 拆分退出维度

为关闭记录和 archive 元数据建立兼容字段，至少表达：

- `exit_mechanism`: `character_accept | user_hard_exit | system_fallback`
- `exit_initiator`: `user | character | system`
- `completion`: `complete | interrupted | unknown`
- `exit_reason`: 固定枚举，不保存完整用户/角色文本

保留现有 `last_exit_type` / summary `exit_type` 作为兼容投影，但新逻辑不得再把它当作完成度唯一真值。旧 archive 没有新字段时返回 `unknown`，不得批量迁移或重写历史文件。

“角色侧退出”指角色通过机器控制合同接受/发起关闭；角色只在可见台词中描写离开，不自动获得系统关闭权限。

## 范围 B：梦境完整度与明信片资格

- 把 postcard 的资格判断抽成独立纯函数，返回 `eligible` 与固定 `reason_code`。
- 至少保留以下条件：单人 sandbox、同一 dream_id 只生成一次、assistant 有效回合数达到阈值、archive 可读。
- 不再使用 `exit_type == hard_exit` 无条件排除。
- `completion == complete` 的梦即使最终通过用户补点硬退出，也可进入明信片生成；真正紧急中断、短梦、损坏 archive 仍不生成。
- 新退出合同生效后的完整度由机器状态写入；旧 archive 缺字段时只能按保守规则推断，并在观测中标为 `legacy_inferred`，不得重写历史 archive。
- 生成失败、资格拒绝、重复、未达回合阈值分别记录固定 reason，不记录梦境正文。
- 计划日期、冻结信文和 SMTP 重试仍沿用现有 `postcards/schedule.json`；成功前不得标记 sent。

## 范围 C：Reality 出梦主动感想可靠性

- 保留 Dream Guard、DND、conversation gate、主动消息预算和正常 Reality pipeline。
- `dream_exit` 仍只在适合主动开口的状态发送，不得在用户正在聊天时插话。
- 为每场待发送感想建立可观测生命周期：`waiting_afterglow | ready | blocked | sent | expired`。
- `blocked` 至少提供固定 `reason_code`：`not_quiet`、`dnd`、`global_gap`、`budget`、`higher_priority_winner`、`afterglow_not_ready`、`send_failed`。
- 一旦 ready，使用有界 aging/优先级提升或专用 durable pending 状态，保证它不会被普通 `topic_followup`、日记提醒等候选无限压住。
- 不允许通过取消 QUIET/DND/预算闸门来“保证发送”。超过有效窗口后明确写 `expired`，不能无痕消失。
- 发送成功后才更新 `last_greeted_dream_id`；失败保留可重试状态。

## 范围 D：后端只读 API 与管理面板

### D1. 梦境 archive API

新增 activity/state.read 合适 scope 的只读端点，建议：

- `GET /dream/archive`：分页列出单人梦境。
- `GET /dream/archive/{dream_id}`：读取单场逐回合记录。

列表只返回安全元数据：dream_id、char_id、开始/结束时间、有效回合数、dream_mode、世界的安全显示名、退出维度、summary 是否存在。不得返回物理路径、context snapshot、hidden state、prompt、密钥或内部绝对路径。

详情只返回回放所需的 `role/content/ts` 与必要展示字段；严格验证 dream_id 和 char_id，路径必须通过 `core.sandbox.get_paths()` / `core.data_paths` 解析，禁止用户输入拼路径。只允许读取 archive，绝不读取 `tmp/current_dream*`。

### D2. 运维观测 API

新增管理面专用只读端点，建议 `GET /dream/operations`，按最近梦境展示：

- archive/summary/afterglow residue 是否存在及时间；
- Reality 主动感想 lifecycle、最近阻断 reason、尝试时间、发送时间；
- postcard eligibility 与 reason_code；
- postcard scheduled_date、sent、attempts、last_error 的安全摘要；
- 当前 dream state、last_dream_id、last_greeted_dream_id 的一致性判断。

不得返回明信片正文、梦境正文、原始 prompt、邮箱地址、SMTP 配置或本机路径。

### D3. 后端管理面板

- 在现有 admin static 信息架构中增加“梦境运维/梦境观测”页面或明确子页。
- 页面提供概览卡、最近梦境表、主动感想状态和明信片队列表；支持按角色筛选和刷新。
- 对 pending、blocked、expired、SMTP failed 使用明确中文说明，不能只显示内部枚举。
- 明确区分“已生成”“已排期”“已到期”“已尝试”“已发送”。HTTP 200 不等于 SMTP 投递成功。
- 全部用户可见文案支持管理面现有中英文机制；移动/新增 fragment 时按缓存版本规则更新。

## 范围 E：主聊天 Sidebar 的梦境回放页

- 在 `Emerald-client` 主聊天窗口现有 Ribbon 增加“梦境回放”侧边栏开关，行为与“日记”按钮一致：再次点击关闭侧栏，与其他 Sidebar tab 互斥切换。
- 在现有 `SidebarPanel`/Sidebar tab 体系中增加独立 `dream-replay` 页面；它不是 Dream overlay 内的 HUD/潜意识侧栏，也不是新的顶层窗口。
- 列表视觉与交互沿用 Chat 页日记侧边栏的密度和页面结构：场次卡片显示日期、角色、持续时间/回合数、模式和简短安全摘要。
- 点击场次后在同一个侧边页面内切换为详情，并提供返回列表操作；不得调用 `WebviewWindow`，不得创建类似 `diary-detail-*` 的独立小窗。
- 详情不是文章排版，而是适配侧栏宽度的只读聊天 transcript：
  - 用户与角色气泡方向明确；
  - 保留原始段落与时间；
  - 历史内容静态显示，不播放逐字动画、不触发 TTS；
  - 没有输入框、发送、编辑、删除、重试或继续梦境操作；
  - 不把回放消息写入 `StateEngine` 当前聊天、不注册 WS 去重、不触发 Reality/Dream pipeline。
- 可复用现有聊天气泡的纯展示层，但不得复用会订阅 WS、写当前会话或自动播放语音的容器。
- 当前活跃梦不出现在 archive 列表；退出完成并归档后刷新才出现。
- 空状态、加载失败、旧 archive 缺元数据、超长梦分页/分段加载均有明确 UI。
- 新增文案全部走 `src/shared/i18n/`，不得追加到 `legacy.ts`。

## 文档同步

- 后端：`docs/dream.md`、`docs/scheduler.md`、`docs/data-taxonomy.md`；若新增管理面观测页，同步相关 admin 文档。
- 桌面：`ARCHITECTURE.md`、`docs/frontend-structure.md`、`docs/backend-integration.md`、`docs/dream-hud.md` 或其当前 Dream 侧栏权威文档。
- 文档不得记录真实用户 ID、邮箱、梦境正文或本机绝对路径。

## 不在范围内

- 不让 archive、回放或明信片进入 Reality memory、episodic、mid_term、identity、mood 或普通 prompt。
- 不允许角色直接读历史 archive；回放方向仅为数据到用户眼睛。
- 不给桌面端增加梦境 debug/运维页；运维观测只在后端管理面板。
- 不修改群聊 Dream Stage 的零回流合同；群聊回放若未来需要，另开 Brief。
- 不迁移、删除或重写真实历史梦境文件。
- 不把自然语言关键词识别当作机器退出合同。
- 不借机重构整个 scheduler、Dream pipeline、ChatPanel 或客户端状态引擎。

## 主要文件

后端预计涉及：

- `core/dream/dream_pipeline.py`
- `core/dream/dream_prompt.py`
- `core/dream/dream_log.py`
- `core/dream/postcard.py`
- `core/scheduler/triggers/dream_exit.py`
- 必要的 durable dream-exit observation/store 模块
- `admin/routers/dream.py`
- `admin/static/pages/`、`admin/static/js/`、`admin/static/i18n.js`、`admin/static/index.html`
- `docs/dream.md`、`docs/scheduler.md`、`docs/data-taxonomy.md`
- 对应 focused tests

桌面预计涉及：

- `src/windows/dream/` 下现有 Dream sidebar/tabs
- 新的 replay list/detail 纯展示组件
- `src/shared/api/backend.ts`、`src/shared/api/types.ts`
- `src-tauri/src/lib.rs` 的 no-proxy Tauri command
- `src/shared/i18n/`
- `ARCHITECTURE.md`、`docs/frontend-structure.md`、`docs/backend-integration.md`

施工前必须按两个仓库各自 `AGENTS.md` 和专题文档重新确认当前文件名；不得覆盖现有并行未提交改动。

## 验收标准

1. 明确退出请求下，角色接受后系统在同一回合完成 archive 和状态切换；可见回复中不泄漏机器控制字段。
2. 模型漏/错控制字段时产生可观测固定结果，不出现“叙事已醒、状态仍 DREAM_ACTIVE”的无声裂缝。
3. `/dream/exit` 和 `/stop` 在所有强度/non-lucid/异常状态下仍立即成功。
4. 一场完整长梦即使最终由补点硬退出，也不会仅因 `hard_exit` 标签失去 postcard 资格；真正中断的梦仍被拒绝并显示 reason。
5. 当前 postcard schedule 可在后端管理面看到 pending、计划日期、尝试次数和发送状态；无需读文件硬等。
6. Reality 主动感想可看到 ready/blocked/sent/expired；用户聊天时不插话，恢复安静后不会被普通候选无限饿死。
7. 桌面 Dream 侧边栏能列出历史单人梦，点击后以聊天气泡只读回放；无输入、无 TTS、无动画、无状态污染。
8. archive 内容只经专用只读 API 返回给已授权客户端，不进入任何现实记忆或 prompt loader。
9. 管理面和桌面端中英文、空状态、错误状态、窄屏/长梦均完成目检；未完成真实 UI 目检则验收状态必须标记 partial。

## 验证

后端：

- focused pytest 使用 `pytest -n auto`，覆盖退出控制缺失/非法/接受、hard exit 不变量、postcard eligibility、主动感想 aging、archive 路径安全、scope 与脱敏、管理面静态/i18n。
- 保留并扩充 Dream isolation 正反样本，证明 archive API 是面向用户的显式例外，但 Reality memory/prompt 仍不能读取 archive。
- 对新增/修改 Python 运行 `py_compile`；管理面 JS 运行 `node --check`。
- fragment 或直接加载静态资源改动按 AGENTS.md 更新缓存版本。

桌面：

- `npm test` 覆盖 API 字段、纯 transcript 映射、旧 archive/空状态处理。
- `npx.cmd tsc --noEmit`、`npm.cmd run build`；涉及 Rust command 时运行 `cargo check`。
- 浏览器/Tauri 目检侧边栏列表、聊天式详情、长梦滚动、语言切换和后端失败。
- 真实联调至少完成一场测试数据隔离环境的 enter → 多轮 → 角色接受退出 → archive 出现 → Reality 感想状态 → 桌面回放；静态 fixture 不替代该 E2E。
- 两仓分别执行 `git diff --check` 并检查未夹带其他 agent 的改动。

## 建议施工顺序与提交边界

本 Brief 是跨仓交付，按依赖顺序拆成独立 commit：

1. **后端退出合同与退出维度**：结构化控制、兼容字段、回归测试。
2. **后端 postcard 与 Reality 感想可靠性**：资格函数、durable lifecycle、aging 与测试。
3. **后端只读 API 与管理面观测**：archive/operations 端点、页面、i18n、文档。
4. **桌面 Dream 回放**：Tauri/API、侧边栏列表、聊天式详情、i18n、文档。
5. **跨仓 E2E 与差异审计**：只补验收证据和必要的小修，不把前四步压成一个大提交。

每一步相关测试和差异检查通过后立即提交，再开始下一步；任一步真实 UI/E2E 未完成时不得把整张 Brief 标为 complete。
