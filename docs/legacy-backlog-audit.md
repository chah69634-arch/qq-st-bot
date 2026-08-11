# Legacy Backlog 审计

> 这是旧产品决策和 bug note 的持续审计日志。应追加新的 batch，不要把本文当作 implementation plan。代码是 release truth；状态为“已实现”不代表已完成设备或发布验收。

## 状态说明

| 状态 | 含义 |
|---|---|
| 已实现 | 请求能力，或明确更强且兼容的替代能力，已经位于 active path。 |
| 部分实现 | 有用部分已经存在，但声明的契约或运行保证仍缺失。 |
| 延后 | 不是当前 implementation target，需要产品/协议决策，或已被其他方案取代。 |
| 开放 | 未找到合适实现。 |

## Batch：交互、记忆、交付与运维

### 交互

| 项目 | 状态 | 审计结果 | 后续 |
|---|---|---|---|
| A. 非对称时间响应语气 | 部分实现 | 已有 prompt layer `2.5_time`、夜间敏感 style hint 和深夜 sensor event，但没有结构化的时间段到表达方式策略。`perception_block` 预留给 pending desktop perception 和跨 channel continuation。 | 若实现，应增加独立可观测的 prompt layer，不要复用 `perception_block`。 |
| B. 缺席后的渐进式“想念” | 部分实现 | 已有 presence attribution、silence ratio 和 `presence_nag`。`presence_nag` 是受保护的桌面 popup（默认 60 分钟、负面 mood、QUIET state、cooldown），不是 15 分钟/1 小时/数小时/一天的升级曲线。 | 创建专用 proposer，并保持 DND、sleep guard、Dream guard、cooldown、lock 和 mobile delivery 不变。 |
| High-pressure-window note | 开放 | Author-note selection 当前只考虑新近程度和未充分表达的 trait。没有把 emotion、relationship state、continuity 和低概率结合起来的 note type 或 selector。 | 增加前先定义 consent、state input、frequency cap、退出条件和 observability。 |

### Prompt/tool 架构

| 项目 | 状态 | 审计结果 | 后续 |
|---|---|---|---|
| Asymmetric probe | 已实现 | Path A probe 只暴露 `info` 和 `desktop`；memory tool 通过 owner-only、function-calling 的 Path C tool loop 暴露。Path C 跳过通用 probe。 | 用 latency、cost、tool completion 和 regression evidence 重新评估，不要只看代码形状。 |
| Query-sensitive prompt trimming | 部分实现 | 当前 trim order 让 episodic memory 比 mid-term memory 更晚保留。Episodic selection 已考虑 relevance，但全局 prompt trimming 仍是固定 layer priority。 | 等待 eval 证明固定 trimming 是瓶颈后再处理。 |
| HTTP 到 SSE/WS 与 channel registry | 已实现/部分实现 | Authenticated desktop/device WebSocket、streaming、turn-sink fanout 和 channel registry 已 active。Mobile 有 durable poll/ack queue。Registry 是 channel-level，不是 multi-client session registry。 | 不要只为 parity 把 WS 换成 SSE。Multi-client delivery 需要版本化 session/client identity 设计。 |
| Apple Watch 准备 | 延后 | 后端接受 narrow-scope watch signal，但这里没有 iOS host 或 WatchConnectivity client。 | 在批准版本化 delivery contract 后，于 iOS/mobile 范围内设计。 |

### Memory 与 recall

| 项目 | 状态 | 审计结果 | 后续 |
|---|---|---|---|
| Importance/significance score | 部分实现 | 没有独立的 `importance: 1-10`；`strength` 由 LLM 初始化并由规则修正，同时有 `is_core`。 | 只有当含义与 strength/retention 不同才增加，否则会重复已有 score。 |
| Semantic recall | 已实现 | sqlite-vec 和 embedding 支持 semantic episodic/event recall；失败时回退到 keyword recall。 | 保持现状。 |
| 统一 `memory.retrieve()` | 开放 | `Pipeline.fetch_context()` 分开加载各层，prompt building 再应用全局 budget。 | 先有需要统一 API 的明确 consumer，再设计。 |
| Provenance | 部分实现 | Append-only provenance 跟踪 write/revision/forget operation，并有只读 query API，包括 self-drift view。但还没有让每个 aggregate point 直接指向明确的 event-log record ID 列表。 | 若需要逐点追溯，增加显式 record-id 关联。 |
| Explicit forgetting/supersession | 部分实现 | Delete、forget-downgrade、revision/correction、closure matching 和 audit trail 已存在，但没有通用的自动 `superseded_by` conflict resolution。 | 先定义冲突语义和人工复核边界。 |
| Structured self model | 部分替代 | 已退役的 `character_growth` 不得恢复。当前 trait state、author-note state、inner diary 和 self-drift provenance 覆盖部分目标，但还不是一个叙事化 self profile。 | 不要重新启用旧模块；先定义统一 profile 的 ownership 和 schema。 |
| E. Episodic score 中的 query relevance | 已实现 | Keyword-IDF relevance 和 semantic similarity 参与 fused recall score。 | 保持现状。 |
| F. Strength decay floor | 已实现 | Episodic recall 使用 0.3 decay floor。 | 保持现状。 |

### 运维与安全

| 项目 | 状态 | 审计结果 | 后续 |
|---|---|---|---|
| Backup/recovery/export | 部分实现，最高运维缺口 | Release updater 备份被替换的程序文件；legacy migration 可以 archive `data/`。两者都不是经过验证的完整 private-state backup/restore/export workflow。 | 实现 snapshot manifest/hash、restore dry-run、recovery drill、retention 和面向 `data`、`userdata`、本地 configuration 的 secret-safe export 规则。 |
| Device identity 与 permission | 部分实现 | Scoped token、profile、WS authentication、rotation 和 revocation 已存在，但没有 device pairing 或按 device 的 memory-read/delivery policy。 | 先定义 device identity 和 per-device scope。 |
| Task queue 与 scheduled work | 部分实现 | Scheduler、maintenance trigger、defer queue、slow queue 和 DLQ 已存在。Defer 与 slow queue 有意保存在内存中，重启会丢失 pending work。 | 若需要恢复，先为 queue 定义 durable ownership 和恢复语义。 |
| Tool sandbox 与 permissioning | 部分实现 | Whitelist、local policy、scope、danger mode、confirmation 和 write envelope 已存在，但这不是 OS/plugin sandbox。 | 在 public plugin/function mod 前单独设计 sandbox。 |
| Install 与 migration | 有限制地已实现 | Config template、auth setup、release updater 和 v1 migration/recovery 文档已存在，但它们不能替代 user-data backup/recovery。 | 以 private-state backup/restore 为优先。 |
| Server hub、admin、diagnostics | 后端范围内已实现 | Pipeline/turn sink/registry、admin route、recall trace、provenance、vector 和 hidden-state observability 已存在。未评估 client UI 完整性。 | 另行审计客户端控制面。 |

### 优先级建议

1. 完整的 private-state backup 和 restore drill。
2. Device pairing、per-device authorization 和 delivery semantics。
3. 缺席曲线与结构化 time-tone layer。
4. 之后再评估统一 retrieve、adaptive trimming 或独立 importance field。

## Batch：5.15 desktop-state 与 mobile-delivery 风险

| 项目 | 状态 | 审计结果 | 剩余风险/后续 |
|---|---|---|---|
| StateEngine ref/observer delivery | 部分实现 | `ChatWindow` 仍在 `useRef` 中保存一个 `StateEngine`，但这是安全的：`StateEngine.applyPatch()` 调用 `emit()`，渲染 consumer 用 React `setState` 订阅。Polling 已调用 `applyBackendState()`。`state-update` source type 已预留，但没有 WS `state_update` frame 被发送或消费。 | Phase 3 必须增加 protocol frame，并路由到 `engine.applyBackendState('state-update', patch)`；增加 focused subscription/render regression test。 |
| 放宽的 `tsconfig.json` | 已记录，可接受债务 | 设置了 `strict: false`、`noUnusedLocals: false` 和 `noUnusedParameters: false`；同时启用 `skipLibCheck: true`。没有找到 `ignoreDeprecations` suppression。 | 作为 migration debt 保留，并按 file/domain 有计划地收紧。 |
| Google Fonts CDN | 开放 | `index.html` 仍 preconnect 并加载 Google Fonts。本地 decorative font 存在，但不能替代 CDN family。 | 在 offline Tauri acceptance 前打包/授权所需 font file，并声明本地 fallback。 |
| Mobile queue destructive poll loss | 已实现替代方案 | Backend poll 非 destructive。Flutter 和 Android 持久化 seen ID，然后确认最大 sequence；ack failure 不会推进 cursor。 | 这提供 at-least-once delivery 加 dedupe，不是通用 exactly-once transaction。 |
| 多台 phone/tablet 消费同一 queue | 开放 | Backend queue 和 acknowledgement cursor 按 owner 而不是 device 维护。一台设备可能在另一台读取前确认消息。 | 需要 device identity 加 per-device cursor/ack state；决定 delivery 是 broadcast、primary-device 还是 handoff。 |
| Mobile token / 公网暴露 | 部分实现 | Mobile credential 使用 Android Keystore，并应使用受限的 `mobile` scope；cleartext origin policy 受限。 | 公网部署仍需要 HTTPS、pairing/device revocation 和明确 threat model。Authenticated client 上存在 token 是正常的；未 scoped 的长期 admin token 不是。 |

## Batch：v0.2 producer、probe、UI 与平台边界

### Producer 与 probe

| 项目 | 状态 | 审计结果 | 后续 |
|---|---|---|---|
| Visual Perception Producer | 桌面已实现；跨设备产品决策部分实现 | Desktop Tauri client 负责 capture。它要求本地 opt-in 和 backend `sensor.write` preflight gate，按 60--3600 秒采样（默认五分钟），拒绝锁定的 desktop，在内存中 hash frame，只上传有意义的变化，并只记录 shadow trace。Backend 永远不把 image 写盘，也不送入 prompt/memory。没有发现 mobile screenshot producer。 | 两个 gate 分别开/关做一次 desktop smoke test 并检查 trace。增加 mobile 前，先定义独立 mobile permission、前台/后台规则、source identity 和 retention contract；不要静默复用 desktop capture 语义。 |
| Probe Capture Wiring | 已实现，但仅诊断 | Active owner-chat path 在 Path C 关闭时与 context retrieval 并行运行 `admin/routers/chat.py::_probe_and_execute_tools()`。它在每个用户的内存五轮 ring 中捕获 system prompt、短 context、raw probe response、requested tool call 和 result，可通过 `/observe/probe` 读取。QQ 有等价 capture path。 | 若认为它损坏，应做一次真实 request smoke test。它重启后有意消失，不是 durable audit ledger。 |
| “Weather 没有使用 probe” | Proactive weather 预期如此；chat 中按条件使用 | 用户 chat 可以通过 Path A 选择 `weather` info tool。function-calling Path C active 时，Path A 会有意跳过，由主 model 负责 tool selection。Scheduler weather alert 直接调用 weather provider，不经过 chat probe。 | 记录一个具体消息的 channel、active tool-loop state、probe snapshot 和 tool trace 后调试；不要让 scheduler 调用 probe。 |
| Standalone mode 与 model/tool routing | 路由层已实现；runtime 验收待做 | Standalone mode 只关闭 QQ 并标记 desktop active。它仍使用同一 owner-chat turn、按角色 model routing、desktop settings model picker 和 Tool Loop settings page。因此启用 Path C 时，它仍会替代 pre-pipeline probe。 | 如果担心的是另一种“single-client/no-probe”模式，应记录准确入口和预期 model。静态审计未发现独立 mode-specific routing gap。 |

### Tool-result envelope 与 EventBus

| 项目 | 状态 | 审计结果 | 后续 |
|---|---|---|---|
| 用于 `chat/tool_call/tool_result/probe_result` 的最小 agent-loop `InteractionEnvelope` | 当前架构延后 | Tool result 已有明确本地 ownership：Path A 为当前 turn 返回一个有界 `tool_result` prompt layer；Path C 在 `run_agentic_loop()` 内保留 tool message；两者都避免重新进入 stimulus gate，也不会默认成为 memory。`PerceiveEvent` 只负责低信任 reality stimulus gate。 | 不要只为了给已有 value 加标签就引入 global envelope。若需要跨进程 replay 或第二个 agent runner，先批准版本化、脱敏、owner-scoped event contract，并定义 retention/idempotency。 |
| EventBus 下一阶段 | 搁置 | Authoritative interaction model 已将 `EventEnvelope`、kind routing、`kind=tool`、`kind=activity`、plugin system 和 unified dispatcher 标为历史/延后。现有 channel 是 downstream fanout，不是 EventBus。 | 只有出现不能由 turn sink、scheduler 或 tool loop 服务的具体 producer/consumer 时才重访。保持“`tool_result` 永不重新进入 stimulus”这一硬边界。 |

### Desktop UI mod path

| 项目 | 状态 | 审计结果 | 后续 |
|---|---|---|---|
| 拆分 chat UI | 部分替代 | `ChatWindow.tsx` 现在主要负责 composition 和 controller wiring；sidebar、ribbon、chat panel、overlay、preference、pane、dream 和 appearance control 都已拆为 component/hook。它仍是 application shell，还不是很小的纯 layout file。 | 只有具体 extension point 需要时才继续；避免为了好看再拆一层。 |
| UI slot 与 class hook | 已实现，范围有意收窄 | `LayoutHost` 通过 `data-layout-slot` 暴露稳定的 `ribbon`、`sidebar` 和 `main` slot；`ChatPanel` 单独约束注册的 main-region template。契约不暴露任意 topbar/right-panel/overlay component replacement。 | 增加 slot 必须有 ownership、state 和 safety contract；任意 React injection 属于 function-mod/plugin work，不是 CSS layout feature。 |
| Layout registry 与 manifest | 已实现 | 内置和磁盘 `layout.json` manifest 经过 layout registry 校验并加载。已有四个 bundled layout example：`sidebar-right`、`mirror-stage`、`focus-stage` 和 `presence-glass-atlas`；支持的 main template 是 `stack`、`workbench` 和 `hud`。 | 保持 registry 声明式。当前 built-in fallback 只有 default layout，因此 example 仍需要 packaging/release 验证。 |
| UI mod guide、example 与 token | 部分实现 | `docs/layout-mods.md` 和 `docs/ui-mods.md` 记录 layout/theme 与 bundled example。Theme token 覆盖 color、shape、font、Dream 和 motion。Layout geometry 通过 manifest 和 registered region 表达，不依赖 `--sidebar-width` 等宽泛 CSS variable。 | 当前约束合理。只有两个真实 layout 需要相同可调尺寸时，才增加 geometry token。 |
| Community/function mod market | 延后 | Theme 和 layout 不执行第三方代码。UI 文档明确将 function mod 延后到 sandbox 和 permission 设计之后。 | 将其当作 plugin/security project，先做 device identity 和 tool sandbox，不要当成 frontend marketplace ticket。 |

### Character API 与 control-plane 审计

| 项目 | 状态 | 审计结果 | 后续 |
|---|---|---|---|
| 将 character 与 chat/memory 打包成 API | 基础部分存在；不是 public platform API | Character card、active-character information、model-routing resolution 和 asset binding 已有 scoped endpoint。`/desktop/chat` 是 owner-only application entry point，位于 live pipeline 之上；其 memory、lock、active character 和 delivery behavior 不是稳定的 embeddable API contract。 | 将未来目标命名为 **Companion Runtime API**，而不是 character API。先做版本化 owner/session identity、`POST /turn`、streamed turn event、明确 memory scope/retention、idempotency key、capability discovery 和隐私安全的 export/import boundary。不要暴露内部 file schema，也不要让调用方选择任意 memory path。 |
| Admin/frontend/backend 不一致 | 部分实现 | 已有大量只读 panel：prompt/probe/tool trace、recall/vector/provenance、runtime、resource completeness、API contract check、feature flag 和 resolved character permission。Desktop setting 还显示 model routing、per-character routing、thinking、tool loop 和 visual local opt-in。它们分散在两个 UI，尚未形成“configured → resolved → runtime observed”视图。 | P0 是 effective-control-plane endpoint 和 page，合并 configured value、inheritance/override、enabled gate、owner process/client version 和 last observed use。不得暴露 secret，并明确显示 client capability 缺失。 |
| Sticker “没有发送” | 路径已实现；运行上未验证 | Backend selection、emotion fallback、feature/probability control、per-character pack、cross-channel payload fanout 和 desktop/mobile rendering 都存在。0.06 默认 trigger rate、关闭 config、缺少 eligible asset folder、client receive toggle 或 live transport 任一因素都可能造成没有可见 sticker。 | 使用 resource-completeness、`/sticker-config`、一次强制高概率 diagnostic turn、log 和真实 desktop/mobile receipt check，再判断是否是 code defect。 |

### Reasoning 可见性与下一阶段系统风险

| 项目 | 状态 | 审计结果 | 后续 |
|---|---|---|---|
| DeepSeek probe 可见性与 “speaking/tool order” | 部分实现 | Probe snapshot 和 tool trace 可以显示已选调用及有界结果。Path C loop 期间 desktop 还收到临时 `tool_status` indicator。它足以做 operator trace，但不是 model-thought display。 | 必要时增加脱敏 lifecycle timeline（`probe decided`、`tool started`、`tool finished`、`reply started`、`reply sent`）和 correlation ID。绝不把 hidden reasoning 做成产品/debug payload。 |
| Chain-of-thought visualization | 不是有效目标 | Native `reasoning_content` 和 inline think tag 会被有意丢弃；生成的 monologue 只注入一个 turn，永不 broadcast、存储或写入 history。 | 保持此边界；使用简短 authored explanation 或安全 decision/tool trace，不提供 raw chain of thought。 |
| State explosion / single source of truth | 部分实现 | 多个 domain 已声明 owner（backend runtime、channel/turn sink、desktop `StateEngine`、memory、Dream/Stage），但没有跨 domain effective-state inventory。 | effective-control-plane audit 是最小有用下一步；不要把无关 state 集中到一个 JSON document。 |
| Schema version 与 migration | 部分实现 | Data-path migration 和 compatibility fallback 存在，但没有覆盖全部 private state 的 universal schema registry、migration ledger 和 restore drill。 | 广泛 schema change 必须绑定 backup/restore 优先项。 |
| Permission 与 trust | 部分实现 | Scoped token、本地 tool policy、confirmation、danger mode 和 source gate 存在。Device pairing、per-device data scope、第三方 plugin sandbox 和 public threat model 不存在。 | 优先于 public API、Watch 或 function mod。 |
| Observability 与 extensibility | 部分实现 | 系统有许多 focused trace 和声明式 theme/layout extension，但没有统一 configuration audit，也没有通用 plugin lifecycle/contract suite。 | 保持当前窄契约；扩展能力前先增加 compatibility 和 capability test。 |

## 证据边界

- 本文是对 backend、desktop client 和 mobile client 的只读 source audit。
- 这些 audit batch 没有运行 test、设备、release build 或 live recovery drill。
- 已保留既有无关 worktree 改动。

## Batch：最终 legacy note —— recall quality、expression 与 content asset

### Live recall 与 proactive expression

| 项目 | 状态 | 审计结果 | 后续 |
|---|---|---|---|
| `spontaneous_recall` 感觉随机 | 部分实现 | Active proposer 只选择最近 candidate window 中最强的 candidate，排除最近 recall 的 memory，并在成功发送后标记 chosen memory/topic。但它仍主要按 strength 和 timestamp 排序，最后由随机选择完成；没有明确的 current-topic 或 relationship-continuity score。旧 direct scheduler routine 也有同一问题，不过 live proposer mode 通常关闭它。 | 增加可追踪 candidate score，并在修改 prompt 前拒绝上下文孤立的 memory。验收需要保留实际交付 recall 及其 topic 的短历史。 |
| 短间隔与互不相连的 proactive message | 部分实现，运行上未验证 | Shared proactive ledger 默认执行 90 分钟 global gap、per-trigger cooldown、daily cap、jitter 和一项 continuity hint。它应防止正常 proposer 聚集，但 emergency path 和 legacy/direct send 是例外。Continuity hint 记录 seed/prompt gist，而不是交付 reply 的 semantic summary。 | 先检查受影响时段的 ledger 和 trigger trace；然后关闭 direct-send bypass，记录简短 reply/topic continuation，不要盲目只提高 cooldown。 |
| Mobile 收不到 proactive message | 已实现且用户确认 | Scheduler send 经过 assistant-turn sink，使用 `fanout="all"`；mobile queue 支持 non-destructive polling、持久 sequence acknowledgement 和 client deduplication。用户已确认 active-message 能送达 mobile。 | 从 active incident list 移除。后续工作是 trigger quality，不是 mobile fanout。 |
| Third-person trigger narration | 部分实现 | 许多 scheduler seed prompt 仍把用户描述为“她”；recall seed 明确写着“你…说给她听”。Short-term history 有 third-person cleanup heuristic，但只在生成后运行且有意保守。 | 安全时把 user-facing trigger seed 换成统一 second-person contract，并为短 reply 增加 output-contract case。不要盲目全局替换：third-person 可能指 NPC 或 quoted content。 |
| 重复的“现在，…”开头 | 部分实现 | Prompt layer 已保留近期开头、注入 no-repeat hint，并持久化 anti-collapse/stream-collapse correction signal。这些检查以 prefix 为主，因此 semantic paraphrase 或 model-specific habitual opener 可能通过。 | 不要加入随机 seed noise。先在固定 eval corpus 上加入 measured recent-opening n-gram/similarity check 和一轮 corrective constraint（或只在违规时低成本 retry）。 |

### Memory、叙事与群聊上下文

| 项目 | 状态 | 审计结果 | 后续 |
|---|---|---|---|
| Temporary 与 long-term profile fact | 部分实现，已有安全 read-side 改进 | Prompt layer 5 只 allowlist 紧凑 objective core field。Tagged preference/habit/health 按 relevance 或 recency 选择；`status.project` 30 天过期。Legacy `stable`/`misc` fact 和 scalar `interests` 仍在磁盘，但不再作为 ambient prompt context。报告的“很长历史概述”还可能来自 identity、episodic、mid-term、pinned fact 或 author note。 | 迁移数据前先导出一个 prompt-layer snapshot 并分类 source。使用 preview-only migration：project/status 为短期；habit/health 为中期；持久 value/relationship stance 进 identity；episodic event 进 episodic memory。保留 provenance，自动 classifier 绝不删除 fact。 |
| Vector total `0`、dimension `1024` | Blocked / observability 含义不明确 | `vector_store.stats()` 对 empty store、database/native extension unavailable、schema error、embedding config 失败、provider failure 或 dimension mismatch 有意都返回同一个 `{total: 0}`。`self_hosted` embedding 明确未实现，只有配置好的 OpenAI-compatible embedding 能写 vector。 | 先做只读 vector health result：DB/native availability、无需 secret 的 configured-provider validation、last embedding attempt/error、dimension 和 per-source count。再做 controlled rebuild/recall case。不能把显示的 zero 当成某一个原因的证据。 |
| Dream narration pronoun | 契约已实现；运行违规需具体 bug example | Dream prompt 已约束 character 使用“我”、用户使用“你”、禁止叙述用户，也禁止用“她”指用户。 | 不要做“她→你”或“我→他”的 render rewrite；它会破坏 NPC reference 和 speaker meaning。捕获问题 reply，在 segment boundary 修 generator/output validator。 |
| Group-chat history timestamp 与排序 | 正常 group context 已实现 | Group-context rendering 按 relevance 给较旧上下文排序，然后按 timestamp order merge，并用 `[timestamp] sender: content` annotation 输出选定 transcript。 | 若问题来自 Stage 或 Dream-stage transcript，应使用具体 payload 审计独立路径；不要复制 normal group formatter。 |
| Two-hop episodic recall | 已实现，默认关闭 | `two_hop_enabled` feature flag 通过 shared topic keyword 扩展，有 two-item hard cap、link-frequency cap、score threshold 和 trace provenance。 | Vector health 与 recall eval 全部通过后再启用；检查 topic drift 后再考虑默认开启。 |
| Tag conflict / insertion order | Worldbook 已实现；episodic recall 部分实现 | `lore_engine` 和 dream-world entry 按 keyword 匹配，再按 `insertion_order` 排序。Episodic memory 有意按 recall score 而不是手工 insertion priority 排名。 | 保持两种语义分离。只有真实 curation workflow 需要时，才为 episodic 增加 manual pin/priority。 |

### UI、输出、成长与打包想法

| 项目 | 状态 | 审计结果 | 后续 |
|---|---|---|---|
| Repository renaming leftover | 文档清理延后 | 用户确认当前 remote backend repo 名为 `PresenceKit`，且 v0.2.3 已发布。除非 remote 确实另行改名，不要把 remote/clone URL 改成 `His-presence`。Local-development/product reference 需按内容判断。历史 sample memory 中的旧项目名不是 repository reference。`buttplug` `ClientName` 是 handshake identifier，不是文档名称。 | 做 content-aware docs-only pass，而不是 global replacement。保留历史 test memory；设备 handshake 只有在 compatibility smoke test 和明确批准后才改。 |
| Personality-dynamics slider | 延后 | 没找到稳定的 component/state contract。 | 先定义它们控制的 observable state，并防止 slider 变成无法追踪的第二 prompt source。 |
| Rich text / emotional typography | 部分替代 | Desktop client 是 React/Tauri，不是 Qt。它只安全解析 `<hl>`、`<big>` 和 `<sm>` inline tag；narrative segment 已有 structured parser。 | 若有具体视觉设计，扩展现有 safe renderer 支持批准的 action/strike/link semantic。永远不要允许 model output 中任意 HTML/CSS。Hover/click behavior 需要明确 interaction 和 accessibility contract。 |
| Dynamic/characterful streaming | 部分实现 | Desktop path 使用 paragraph-safe buffering streaming；Dream 有 pseudo-stream typewriter replay。没有 mood-to-speed/chunk policy 或 action-first scheduler。 | 输出质量问题修复后再增加 display-layer pacing controller，使用完整 safe segment，而不是 raw token chunk。Yandere overlay/mouse reaction 应作为单独、经同意的桌面 visual feature。 |
| Autonomous knowledge growth | 部分实现 | X3 web search 可以将外部来源写入 vector storage，并使用 feature flag 触发 tool use。未发现无人值守的通用 web-crawl-to-`yexuan_notes` job。 | 保持 background research opt-in、限频、有 attribution、可 review，并与 personal memory 隔离。“Self-awareness”和改变 model weight 不是 runtime product feature。 |
| Mood-driven temperature | 只有基础 | Model preset 会传递普通 provider parameter，包括 `temperature`；没有由 mood/scenario resolver 控制它。 | 若增加，应采用系统选择的 deterministic scene/relationship mapping，按 request log、受 preset/provider limit 约束，并做 regression evaluation。 |
| DS draft 加 Claude polish | 延后 | Multi-preset routing 存在，但没有 draft/critic/rewrite pipeline。 | 不要在 output evaluation 前加入：它增加 model round trip，可能抹掉 voice 或 memory grounding。只用固定 rubric 和 side-by-side example 做 prototype。 |
| Worldbook 与 export | 部分实现 | Keyword lorebook 支持 `insertion_order`；Reality 与 Dream 有独立管理路径和 JSON-oriented import/export。统一 global/per-character worldbook taxonomy 与 Tavern-compatible interchange 尚未成为单一 active product contract。 | 先决定 scope inheritance 和 collision rule，再增加 import/export adapter；不要暴露 private memory。 |
| Static asset classification | 已实现基础 | Authored private asset 通过 `userdata`/asset registry 路由；release-owned example 位于 `bundled`。 | 继续让 asset 与 memory、plugin 分离；只有新 asset category 有 lifecycle/permission requirement 时才扩展 registry。 |
| Dynamic Author's Note placement | 延后 | Note 被轮换并作为固定 late layer 11 注入，与 consistency 和 style correction 并列。 | Placement 会改变 attention 和 safety behavior；先把它作为 prompt variant 测试，再考虑配置化。 |
| “Diary detection” | 开放/定义不足 | Diary read/reminder flow 存在，但没有发现检测用户当前是否正在写 diary 的契约。 | 先明确 source：pasted text、opt-in local file/editor watcher，还是 client activity signal。它们有不同的 consent 和 privacy requirement。 |

## 完整 backlog 审计后的组合优先级

如果目标是**产品信任与沉浸感**，按以下顺序执行：

1. **让 live failure 可观测，再修复：** vector health/rebuild，以及一条 session 的 proactive delivery trace（trigger、ledger decision、fanout、mobile receipt、reply/topic）。把当前“0 vector / 奇怪 spontaneous message”报告变成可证伪的 bug，而不是 prompt 猜测。
2. **保护不可逆的私有状态：** 完整 backup、restore dry-run、recovery drill，以及 private data/configuration 的 manifest coverage。在 memory migration 或广泛 multi-device 工作之前完成。
3. **恢复对话连续性：** 按 relevance 和 recent conversation 给 spontaneous recall 打分/过滤，强制 second-person trigger/output contract，并加强 opening-diversity evaluation。Mobile proactive E2E 必须纳入验收。
4. **干净地分类现有 memory：** 使用 prompt-layer snapshot 和 preview-only、保留 provenance 的旧 profile fact migration。在已知 vector health 前，不要开始 two-hop recall 或更激进的 semantic retrieval。
5. **让 control plane 可读：** 先做一个 effective-config/runtime-observation view，再在 Watch、public runtime API 或 function mod 前做 device pairing/per-device cursor。

本 batch 的其他内容——dynamic temperature、双 model polish、宽泛 rich-text effect、personality slider、UI marketplace、autonomous research 和 dynamic Author's Note placement——都应等这些基础具备 evidence 和 regression coverage 后再做。

## 审计后确认的修正

- Mobile 正确接收 proactive message；当前临时 containment 是更高的 global cooldown，个别 trigger 等待重新设计。
- Local toy MCP integration 已连接，不再是 integration blocker；其 permission 和 recovery boundary 仍相关。
- 当前 remote backend repository 是 `PresenceKit`，v0.2.3 已发布。这是用户确认的 release state，本审计未独立通过网络验证。

## Backup 与 recovery 的实现形态

现有 updater backup 是**程序 rollback** snapshot。它在升级时保护 private root，但不是 private-state backup，不能这样对外描述。

### 第一阶段交付：保守且可恢复

1. 增加 offline/maintenance-only 的 `backup-state create` command。第一版必须在服务运行时拒绝，而不是在 queue 和 memory file 变化时尝试 live copy。
2. 精确 snapshot 受保护的 private state：`data/`、`userdata/`、`config.yaml`、可选的 `config.local.yaml` 和 `secrets.local.yaml`。排除 source code、`bundled/`、environment、只有在明确分类后才可排除的可再生 cache，以及 updater program backup。Backup destination 必须在安装目录外。
3. 在临时 sibling directory 构建 archive，枚举每个 included file，计算 SHA-256 和 byte count，然后写入 versioned manifest，包含 product version、layout marker/schema、创建时间、included root 和 hash。Manifest 或 command output 永远不能放 token plaintext。
4. 对 portable/off-machine archive 加密。本地 archive 可以依赖明确选择的 protected volume，但命令必须报告这一 protection choice，不能暗示已加密。保留小型 rolling policy（例如七份 daily 和四份 weekly snapshot），不能删除最新的已验证 snapshot。
5. 增加 `backup-state verify`（hash、archive readability、manifest/schema）和 `backup-state restore --target <empty-directory>`。Restore 默认拒绝非空 target，永远不覆盖 live installation。
6. Recovery drill：停止服务；创建 snapshot；恢复到新目录；验证 hash 和 data layout；运行 authored-root dry-run；只在 standalone/no-outbound mode 启动；证明 configuration/auth/character/pipeline initialization；再将一个选定的 memory、authored asset 和 dream/state record 与 manifest 比较。只有完成这些步骤后，人才能显式切换 live installation。

### 验收与迁移规则

- 只有 `verify` 通过且至少一次 restore drill 成功，才能称 archive 已 backup。
- Migration 或 profile reclassification 前必须先创建并验证 snapshot；恢复使用目录级 restore，不是原地 downgrade。
- 失败必须记录为结构化、无 secret 的结果：missing root、unreadable file、hash mismatch、unsupported layout、restore target non-empty 或 startup validation failure。
- 增加 file selection、manifest tamper detection、missing optional config、拒绝 live/non-empty target 和 restore round-trip 的 focused test。最终验收仍需要一次真实的本地 recovery drill。
