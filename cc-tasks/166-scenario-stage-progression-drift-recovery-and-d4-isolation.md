# Brief 166：Scenario 剧本推进、偏离拉回与 D4 现实快照隔离

## 背景与现场结论

单人 Dream 的 Scenario 模式目前存在三个相互放大的缺口：

1. 阶段推进只依赖主聊天模型在回复末尾连续两轮给出合法
   `<scenario_control>`，并连续两次把 `progress_signal` 写成 `satisfied`。任意一轮
   `approaching`、`not_close`、控制块缺失或格式非法都会把 `satisfied_streak` 清零；若启用
   `scenario_arc_mode=arc`，当前张力桶未达到 stage `arc` 时还会静默阻止推进。真实对话中这套
   条件很容易长期无法同时成立，使剧本停在第一阶段。
2. 模型上报的 `blocked_events` 只写入 `ScenarioCore.last_blocked_events`，之后没有任何消费方。
   下一轮 DS prompt 不会看到偏离结果，也没有自然拉回当前 `dramatic_task` 的导演指令。
   `drift_pressure` 仅按总轮数到点注入，不等同于偏离纠正。
3. `D4_frozen_reality` 没有 Scenario 门控。只要 frozen snapshot 能格式化出内容，它就会进入
   实际 system prompt；观测页显示全程 injected 是运行时真相，不是展示误报。D4 中最近现实对话
   虽会在若干轮后衰减为 gist，但 profile impression、episodic、mid-term、relationship state、
   entry reason 仍可能持续存在。Scenario 已硬关闭 D4.5 hidden state 和 D5 body projection，D4
   也应按同一隔离原则关闭。

本 Brief 只修单人 Scenario pipeline。群聊 Dream Stage、Sandbox、Mirror 和 Reality pipeline
不在本单范围。

## 产品决定：谁判断剧情有没有推进

### v1 不新增独立裁判小模型

继续由本轮负责生成可见剧情的主模型同时输出结构化进度观察，原因是：

- 它已经持有本轮用户输入、当前 stage 约束和自己刚生成的可见回复，拥有最完整的局部语义；
- 新增裁判模型会增加每轮一次 LLM/网络往返、延迟和费用，并引入“生成模型与裁判模型各判一套”
  的不一致；
- send/关键路径不得为了判定再 await 第二次 LLM；异步裁判又会产生回复已送达、阶段稍后才改变的
  竞态与下一轮读旧状态问题。

但系统不得继续无条件相信一个笼统的 `progress_signal=satisfied`。主模型只负责提交“观察结果”，
Python 侧用当前 stage 的白名单和确定性规则决定是否推进：

- control 只能引用当前 stage 已注入的 `exit_signs` / `not_yet_allowed`；未知项全部丢弃并记观测；
- `satisfied` 必须同时带至少一个经白名单验证的当前阶段完成信号，否则降级为无效判定，不推进；
- 命中至少一个合法完成信号后，本轮即可顺序推进下一 stage，不再要求第二轮重复确认同一件已经发生的事；
- `approaching` 表示有进展但尚未完成，不推进，也不应像当前实现一样破坏已经明确发生的合法完成事实；
- 控制块缺失/非法时保守地不推进，但不得让阶段永久失去 drift/recovery 能力；
- 主模型无权指定 `next_stage`，下一阶段仍只由 YAML 顺序和 `scenario_loader.get_next_stage()` 决定；
- arc 模式若阻止推进，必须留下固定 reason code，且 DS 下一轮明确提示还差哪个张力方向，不能静默卡住。

这里的“白名单验证”只能验证模型引用的是当前阶段允许的完成信号，不能用字符串规则证明自然语言
事件真的发生过。若上线观测证明主模型仍系统性误判或漏判，另开二期评估异步/专用裁判；不得在本
Brief 暗中增加第二模型调用。

## 目标

1. Scenario 阶段在当前完成条件确实被主模型命中后可靠顺序推进，不再依赖连续两轮重复打勾。
2. 用户或剧情偏离当前阶段时，下一轮能自然接住用户并把叙事拉回当前戏剧任务，而不是生硬拒绝或继续漂走。
3. Scenario prompt 永不注入 `D4_frozen_reality`，观测准确显示硬关闭原因。
4. 推进、阻断、偏离和纠偏均可通过现有 Dream state/prompt inspector 的安全字段验证，不读取梦境正文。
5. Sandbox、Mirror、群聊 Dream 与硬退出合同零回归。

## 范围 A：确定性阶段推进判定

### A1. 收紧主模型控制合同

- 保留 `<scenario_control>` 在可见回复、dream log、archive 和后续 history 前剥离的现有合同。
- DS 只展示当前 stage，并将当前 `exit_signs` 和 `not_yet_allowed` 编号或以可精确回传的形式列出。
- 主模型返回：
  - `progress_signal`: `not_close | approaching | satisfied`
  - `matched_exit_signs`: 仅引用本轮实际发生的当前 stage 完成信号
  - `blocked_events`: 仅引用用户本轮实际尝试的当前 stage 禁止事项
- 解析器继续兼容现有自然语言控制块和历史 JSON 控制块；不得把未知 `next_stage`、后续阶段名或任意
  自由文本当成推进指令。
- 不允许扫描可见剧情关键词来猜阶段完成，避免角色在假设、否定或回忆中提到完成信号造成误推进。

### A2. 归一化与推进规则

- 在 `dream_pipeline.py` 中把“解析控制块”与“按当前 stage 归一化/裁决”拆成可单测纯函数。
- 对 `matched_exit_signs` / `blocked_events` 去重，并只保留当前 stage 白名单成员；未知值记录数量或固定
  reason，不记录完整自由文本。
- `progress_signal == satisfied` 且合法 `matched_exit_signs` 非空：
  - linear 模式立即推进到 YAML 中下一 stage；
  - 已是最后 stage 时 `mark_completed()`；
  - 新 stage 从 `stage_turns=0` 开始，过渡轮仍属于旧 stage。
- `satisfied` 但无合法命中：不推进，记录 `satisfied_without_valid_exit_sign`。
- `approaching` / `not_close` / missing / invalid 均不推进，并写固定 disposition。
- 保留 `satisfied_streak` 读取兼容，避免旧进行中状态无法反序列化；新判定不得再要求 streak 达到 2。
  若字段退役，应分独立删除 Brief 清理 schema、测试与文档，本单不强行迁移或重写进行中的真实状态。

### A3. arc 门控可解释

- linear 仍是默认行为。
- `scenario_arc_mode=arc` 且完成信号已合法命中、但张力桶未达到 stage `arc` 时：
  - 不推进；
  - 写固定 `advance_blocked_reason=arc_target_not_reached`、当前/目标粗粒度桶；
  - 下一轮 DS 注入自然的张力导演提示；
  - 不暴露精确张力数值。
- 达标后的下一次合法完成命中正常推进。不得因一次旧命中在若干轮后自动无条件跳阶段。

## 范围 B：偏离检测后的自然拉回

### B1. 将 blocked observation 变成下一轮输入

- `last_blocked_events` 不再只是死字段。经当前 stage 白名单过滤后，下一轮 DS 注入一次受控的
  recovery block。
- recovery block 必须表达：
  - 接住用户刚才的意图，不指责用户“偏离剧本”；
  - 不执行 `not_yet_allowed` 对应事件；
  - 通过环境变化、角色动作、信息缺口或新的局部压力，自然回到当前 `dramatic_task`；
  - 不剧透后续 stage，不宣布系统正在纠偏，不替用户决定动作或台词。
- 当前 stage 变化时必须清空旧阶段的 recovery 状态，禁止把上一阶段的禁止事项带进新阶段。

### B2. 停滞加压

- 区分 `stage_turns` 与连续停滞：新增或等价维护有界 `stall_turns`/`recovery_pending` 状态。
- `not_close`、缺失/非法控制块可增加停滞计数；`approaching` 应降低或清零停滞；合法推进后清零。
- `drift_pressure.after_turns` 应基于明确的停滞语义触发，或至少在文档和代码中明确它到底使用
  `stage_turns` 还是 `stall_turns`，不能继续名为 drift、实际只看总轮数而无观测。
- 达到阈值后注入当前 stage 自己的 `drift_pressure.instruction`；后续 stage 内容绝不泄漏。
- 没有 `drift_pressure` 的剧本仍使用通用轻量拉回提示，但不得凭空创造剧本事实。

## 范围 C：Scenario 硬关闭 D4_frozen_reality

- `build_dream_prompt()` 在 `dream_mode == "scenario"` 时不调用/不消费 D4 snapshot formatter，且不把
  D4 内容追加进 system layers。
- Dream prompt inspector 仍保留 `D4_frozen_reality` 记录，但必须是：
  - `injected=false`
  - `flags` 含 `DISABLED`
  - `note="scenario_mode"`
- 不只隐藏观测记录；测试必须反向证明最终发给 LLM 的 messages 中没有最近现实对话、profile
  impression、episodic、mid-term、relationship state 或 entry reason 的 D4 块。
- 本 Brief 不要求停止入梦时构造整个 frozen snapshot；是否进一步减少 Scenario entry 的无用读取和
  数据驻留另开性能/最小化 Brief。当前验收真值是“Scenario LLM 不消费 D4”。
- Sandbox / Mirror 保持现有 D4 与 reality-context 衰减行为；群聊 Dream 维持自己的固定 card-only 合同。

## 范围 D：只读观测

依照“新增落盘状态必须有只读观测端点”的工程规则，复用并扩充现有 `/dream/state` 和 Dream prompt
inspector，不另造保存正文的台账。安全观测至少提供：

- `scenario_core.current_stage_id`
- `stage_turns` 与采用后的 `stall_turns`/recovery 状态
- 最近一次归一化 `progress_signal`
- 合法命中数量、被丢弃的未知命中数量
- `advance_disposition`: `advanced | completed | approaching | not_close | control_missing |
  control_invalid | satisfied_without_valid_exit_sign | arc_blocked`
- `advance_blocked_reason`（如有）
- `recovery_pending` 和偏离项数量；不得返回完整用户输入、角色回复或未脱敏自由文本
- prompt inspector 中 DS recovery/drift 是否注入、D4 的 `scenario_mode` 硬关闭原因

写观测失败必须 fail-open，不得影响 Dream 回复或硬退出。

## 数据与兼容

- `ScenarioCore.from_dict()` 必须兼容旧状态缺少新字段。
- 不迁移、不删除、不重写真实进行中 Dream、历史 archive 或 authored scenario YAML。
- authored scenario 仍走 userdata-first 与 legacy 只读 fallback；本 Brief 不改变 CRUD/路径优先级。
- 现有 `exit_signs: list[str]` 和 `not_yet_allowed: list[str]` 保持可用；如内部使用编号，只能是 prompt/
  parser 的会话内投影，不强迫用户迁移 YAML。
- 所有状态路径继续通过 `core.sandbox.get_paths()` / `core.data_paths` 获取。

## 不在范围内

- 不新增第二个 LLM、裁判模型、embedding 相似度或关键词扫描来判断推进。
- 不让模型选择任意 next stage，不实现分支、多结局或图式剧本。
- 不把 Scenario 接入 Reality memory、hidden state、impression、afterglow 或普通 prompt。
- 不修改 Dream hard exit、soft wake/retention、archive、postcard 或 scheduler 合同。
- 不修改群聊 Dream Stage。
- 不借机重写整个 Dream pipeline、body tracker、张力系统或 Scenario 编辑器。
- 不修改或清理真实用户 Dream 数据来制造测试通过。

## 预计主要文件

- `core/dream/dream_prompt.py`
- `core/dream/dream_pipeline.py`
- `core/dream/scenario_core.py`
- 必要时 `core/dream/scenario_loader.py`
- `admin/routers/dream.py` / 现有 Dream observe 路由（仅扩展安全只读字段时）
- `docs/dream.md`
- `tests/test_dream_scenario_control_protocol.py`
- `tests/test_dream_scenario_stage_progression.py`
- `tests/test_dream_scenario_stage_content.py`
- 新增窄测试文件（若现有文件接近项目行数限制）

施工前必须重读 `AGENTS.md`、`DESIGN.md`、`docs/dream.md`、`docs/prompt-layers.md`、
`docs/runtime-lifecycle.md`、`docs/interaction-event-model.md`、`docs/security_model.md` 和
`docs/dev-environment.md`，以当前实现与进行中 Brief 为准。

## 验收标准

1. Scenario 最终 LLM messages 中不存在 D4 frozen reality 内容；prompt inspector 明确显示
   `D4_frozen_reality: DISABLED / scenario_mode`。
2. 主模型一次返回 `satisfied` 且至少引用一个当前 stage 合法 exit sign 后，linear 模式在该轮可靠
   推进下一阶段；无合法命中时绝不推进。
3. 模型伪造未知 exit sign、返回后续 stage 名、带 `next_stage` 或控制块非法时均不能推进。
4. arc 模式未达目标时不推进且有可读 reason；达到目标后的合法完成命中能推进。
5. 用户触发当前 stage 的 `not_yet_allowed` 后，下一轮 DS 出现一次自然拉回指令；不泄露“系统纠偏”、
   不执行禁止事件、不注入后续阶段。
6. 连续停滞达到阈值后当前 stage 的 drift pressure 生效；出现 approaching/推进后停滞状态按合同复位。
7. Sandbox、Mirror 的 D4 行为不变；Scenario 的 D4.5/D5 继续硬关闭；群聊 Dream 测试无回归。
8. `/dream/state` / prompt inspector 能在不返回正文的前提下解释最近一次为何推进、未推进或拉回。
9. 旧 ScenarioCore 状态和旧 YAML fixture 仍可加载；不迁移、不改写真实数据。

## 验证

- focused pytest 必须使用项目约定的并行入口，至少覆盖：
  - Scenario D4 正反样本与 inspector note；
  - 合法单次完成推进；
  - satisfied 无合法命中；
  - 未知/跨阶段命中与 `next_stage` 注入攻击；
  - missing/invalid control；
  - arc 阻断及达标推进；
  - blocked event 下一轮拉回及 stage 切换清空；
  - stall/drift 阈值；
  - Sandbox/Mirror D4 保持；
  - Scenario isolation、hard exit 既有回归。
- 对修改 Python 运行 `py_compile`。
- 若改 admin 静态 JS，运行 `node --check`，并按 AGENTS.md 更新 fragment/asset cache version。
- 执行 `git diff --check`，再次确认未夹带其他 agent 的 `cc-tasks`、真实数据或无关改动。
- 至少在测试隔离环境完成一场多阶段 scenario：进入第一阶段 → 制造一次偏离 → 下一轮拉回 → 命中
  合法 exit sign → 进入第二阶段。mock/纯函数测试不能替代这条真实 pipeline E2E；未完成时状态为 partial。

## 建议施工顺序与提交边界

1. **D4 Scenario 隔离**：prompt 门控、inspector 标注、正反测试、`docs/dream.md`，独立 commit。
2. **推进裁决与观测**：白名单归一化、单次合法命中推进、arc reason、兼容字段与 focused tests，独立 commit。
3. **偏离拉回与停滞压力**：recovery/stall 状态、DS 注入、观测与 focused tests，独立 commit。
4. **多轮测试环境 E2E 与差异审计**：只补验收证据和必要小修，不把前三步压成一个大提交。

每一步相关测试和差异检查通过后立即提交，再开始下一步。真实多轮 E2E 未完成时不得把整张 Brief
标记为 complete。
