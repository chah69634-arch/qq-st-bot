# Brief 169：Scenario 专用 Prompt Profile、最小控制合同与梦境运维观测

## 背景与现场结论

Scenario 已硬关闭 D4 frozen reality、D4.5 hidden state 与 D5 body projection，并支持角色卡
`presence_ext.dream_behavior.scenario_directive`。但 D1 仍整段注入通用角色卡的
`system_prompt + description + personality`，D2/D3/D6/D7/D8 等也与 Sandbox 共用。现实/日常关系
策略或自由梦境导演规则可能压过 DS 当前阶段，形成“口头威胁但不产生改变现场的行动”。

当前阶段控制合同还要求主模型输出：

- `progress_signal`
- `matched_exit_signs`：精确照抄当前 stage 的完整 `exit_signs` 文本
- `blocked_events`：精确照抄完整 `not_yet_allowed` 文本

后端再用精确字符串做白名单匹配。模型即使正确演完剧情，只要缩写、改写或漏一个字段，也会得到
`control_missing`、`control_invalid` 或 unknown hit，导致阶段不推进。这一合同对自然生成模型过重。

## 最高优先级边界：Reality 角色卡链路不可回归

Dream 只是玩法之一。本 Brief 不得修改 Reality chat 对 Character 的语义：

- 不改变 `Character.system_prompt`、`description`、`personality`、`scenario`、`mes_example`、
  `post_history_instructions`、`post_history_extra` 的加载、缓存或默认值。
- 不修改 `core/prompt_builder.py` 对上述字段的 Reality layer 组装、顺序、裁剪或 sanitizer。
- 不把 Scenario 的字段裁剪结果写回 `Character` 对象，不原地 mutate，不影响 Stage、scheduler、growth、
  activity companion、eval 或其他消费者。
- 施工前必须重新执行全仓 call-site inventory。当前已知消费者至少包括：
  `core/prompt_builder.py`、`main.py` 快路径/探针角色摘要、`core/stage/views.py`、
  `core/activity/companion_context.py`、`core/growth/practice_session.py`、scheduler interest seed 与 eval。
- 优先新增 Dream-only 纯投影 helper；不要改 top-level Character dataclass 字段。若确需新增 authored 字段，
  只能放在可选的 `presence_ext.dream_behavior` 下，缺失时保持旧卡行为，并补齐 admin 读写、loader、
  cache、导入导出及所有消费者审计。

## 产品决定 A：一条 pipeline，两个 Prompt Profile

- 不复制第二套 `dream_turn()`、状态机、退出协议、history 或 LLM 调用链。
- `build_dream_prompt()` 内建立明确的 `sandbox` 与 `scenario` profile，通过 Dream-only helper 选择层。
- Sandbox、Mirror、Group Dream 保持当前 Prompt 合同；本 Brief 只改变单人 Scenario。

### Scenario profile 的必要层

- D0：破限 preset。
- D1S：Scenario 角色投影，只包含身份/外貌、基础性格、说话方式、人称和不替用户行动的硬约束。
- D8S：Scenario 专用导演/渲染层，要求角色把 stage 立场落实为改变现场状态的行动。
- DS：当前 stage 的任务、压力、约束、私密真相披露规则和机器控制合同。
- DX：不可消融退出协议。
- D9：当前 Dream 历史。
- D10：当前用户消息。

默认不把通用 D1 system_prompt、D2 world rules、D3 example、D4/D4.5/D5、D6、D7、DM 或 Dream
lorebook 注入 Scenario。若未来某个剧本需要专属世界规则，应进入 scenario schema 的显式 authored
字段并另开兼容设计，不允许静默重新借用 Sandbox 世界包。

### D1S 角色投影

- 可新增可选 `presence_ext.dream_behavior.scenario_identity`，让作者写一段专门用于 Scenario 的
  “外貌 + 基础性格 + 说话方式”摘要。
- 缺失时只读 fallback 到现有 `description` 与 `personality` 的有界投影；绝不 fallback 到完整
  `system_prompt`、Reality `scenario` 或 post-history 指令。
- 现有 `identity_anchor`、`sandbox_directive`、`scenario_directive` 的兼容语义需明确：
  `sandbox_directive` 只进 Sandbox；`scenario_directive` 只进 Scenario；不得交叉。
- 管理面角色编辑器若新增 `scenario_identity`，必须明确写“仅 Dream Scenario 使用，不影响 Reality
  chat”，并完整 i18n。

### D8S 行动导演

- 保留 say/do/env/feel 的输出格式，使客户端渲染合同不变。
- 明确“只有口头威胁、重复警告或气氛描写不算推进”；除非 stage 明确要求观察/停顿，本轮至少产生一个
  改变位置、信息、资源、限制或选择空间的角色行动。
- D8S 不得替 DS 决定角色立场、完成条件、下一阶段或用户动作。

## 产品决定 B：最小 Scenario Control v2

### 当前阶段短 ID 投影

- DS 把当前 stage 的 `exit_signs` 映射为会话内短 ID：`E1`、`E2`…；把
  `not_yet_allowed` 映射为 `B1`、`B2`…。
- Prompt 可展示 `E1 — <作者原文>` 供模型理解，但模型回传只允许短 ID，不再照抄整段文字。
- ID 只在当前 stage 有效，阶段切换立即重新生成；模型无权提交 stage ID 或 next stage。

### 最小输出

模型只需追加：

```text
<scenario_control>{"hit":["E1"],"blocked":[]}</scenario_control>
```

- `hit` 是唯一必需字段，可为空数组；存在合法 hit 时，Python 推导为 satisfied 并按现有 linear/arc
  规则裁决。
- `blocked` 是可选字段；只接受当前 stage 的 `B*`，缺失等价空数组。
- 删除对模型必填 `progress_signal` 的要求。无合法 hit 时统一为 `no_progress`；停滞计数由后端现有状态
  与合法 hit/blocked 确定，不要求模型再区分“未接近/正在接近”。
- parser 在过渡期兼容旧 JSON 与“进展/命中/越界”自然文本，但新 Prompt 只教 v2；兼容 parser 不得把
  长文本或未知 ID 当作合法命中。
- control 在展示、archive、history、TTS 前剥离；缺失/非法保守不推进，但不影响可见回复。

### Schema 可推进性

- 每个需要进入下一阶段的 stage 必须至少有一个 `exit_sign`；最后 stage 也应有完成信号才能标记 completed。
- 新建/编辑时阻止保存“永远不可推进”的新剧本，并指明 stage；既有 legacy YAML 继续可读，但列表/编辑器
  标记 `unprogressable`，不自动迁移或重写。
- 不新增第二个裁判 LLM、关键词扫描、embedding 或 send 前网络往返。

## 范围 C：梦境运维中的阶段观测

观测固定进入“后端管理面板 → 观测 → 梦境运维”，复用现有 `/dream/operations` 页面与 API，不另造
顶级页面或客户端 debug UI。

### 持久化审计

新增有界、正文无关的 scenario progress audit；路径必须经 `core.data_paths` / `get_paths()`，并由
`/dream/operations` 提供只读投影。每轮最多记录：

- dream_id、char_id、时间、turn index
- prompt profile/version
- current stage ID
- control status/version
- 合法 E/B ID 数量与安全 ID 列表
- unknown ID 数量（不保存原始未知文本）
- disposition/reason：`advanced | completed | no_progress | control_missing | control_invalid |
  arc_blocked`
- from/to stage ID（仅推进时）
- stall_turns、recovery_pending

不得记录用户输入、角色回复、剧本正文、exit_sign 原文、private truth、Prompt 或本机路径。写审计失败
fail-open，不能阻断 Dream reply、阶段推进或硬退出。

### 管理面展示

- 梦境运维最近梦境详情增加“剧本推进”卡：当前/最终 stage、最近控制状态、合法命中、未识别数量、推进
  reason、连续停滞、最近一次 stage transition。
- 固定 reason 全部中英文解释；不只展示内部枚举。
- Prompt inspector 同时显示实际 profile 与每个被 profile 排除的 layer 的 `DISABLED/scenario_profile`。
- 管理面不能显示私密真相、剧本全文或对话正文。

## 数据与兼容

- `ScenarioCore.from_dict()` 继续读取旧字段；control v2 不要求迁移进行中的真实 state。
- legacy control parser 设明确退役窗口和测试，未来删除另开删除 Brief。
- authored YAML 保持 userdata-first/legacy read-only fallback，不批量迁移或覆盖。
- 新 audit 有容量上限/轮转策略和只读端点，符合新增落盘物观测规则。

## 不在范围内

- 不修改 Reality Prompt、角色卡加载结果、普通聊天、Stage 群聊、scheduler、growth 或 activity 行为。
- 不新增独立裁判模型、第二次 LLM 调用、分支图、多结局编辑器或关键词完成判定。
- 不让 Scenario 接入 Reality memory、afterglow、hidden state 或 impression。
- 不改变 hard exit / DX 协议；退出闭环由 Brief 170 处理。
- 不修改回放渲染；由 Brief 168 处理。

## 预计主要文件

- `core/dream/dream_prompt.py`
- Dream-only scenario profile/projection helper（新模块或本文件纯函数）
- `core/dream/dream_pipeline.py`
- `core/dream/scenario_loader.py`
- `core/dream/scenario_core.py`
- `core/data_paths.py`
- scenario progress audit 模块
- `admin/routers/dream.py`
- `admin/static/pages/observe-dream-operations.html`
- `admin/static/js/dream-operations.js`
- `admin/static/i18n.js` 与缓存版本文件
- `admin/static/pages/character.html` / `admin/static/js/character.js`（仅采用 nested authored field 时）
- `docs/dream.md`、`docs/prompt-layers.md`、`docs/data-taxonomy.md`
- focused Dream/Reality/admin tests

## 验收标准

1. 给同一 Character 和相同 Reality 输入，Brief 前后的 `core/prompt_builder.py` 输出逐层等价；Reality
   system_prompt/description/personality/scenario/examples/post-history 无变化。
2. Sandbox、Mirror、Group Dream Prompt 层和行为零回归；Scenario inspector 显示独立 profile。
3. Scenario LLM 不再收到完整通用 system_prompt，也不消费 Sandbox D2/D3/D6/D7/lore 等层。
4. D1S 只包含 Scenario 专用身份投影；缺失新 nested 字段时旧卡安全 fallback，且不修改 Character 对象。
5. 模型只回传短 ID；单次合法 `E*` hit 即进入确定性裁决，改写/漏填旧长文本字段不再成为失败条件。
6. 模型不能选择 next stage，未知/跨阶段 ID 不推进；control 缺失/非法不泄漏且不崩。
7. 新剧本不会保存为无完成信号的永久卡死结构；legacy 不可推进剧本可读且明确告警。
8. 梦境运维能在不展示正文的前提下解释最近一轮为什么推进或没有推进，并能查看已结束梦的安全审计。

## 验证

- 先固化 Reality 基线 fixture，再运行 focused `pytest -n auto` 比较 Prompt layers/content/order；覆盖
  `core/prompt_builder.py`、main quick context、Stage view、activity/growth 等已知 Character 消费者。
- Scenario focused tests：profile allow/deny matrix、nested field fallback、不 mutate Character、E/B 映射、v2
  parse、legacy parse、unknown/cross-stage、arc block、last stage complete、unprogressable schema。
- admin/API tests：audit 脱敏、容量、scope、fail-open、operations/i18n/static cache。
- `python tests/run_eval.py` 仅当 Reality tag/layer 代码确实被触及；按边界正常施工时不应触及。
- `py_compile`、`node --check`、浏览器目检 Dream operations 与角色字段说明；未目检则 partial。
- `git diff --check`，确认未修改真实角色卡、剧本、data/runtime 或 userdata。

## 建议提交边界

1. Character consumer 基线与 Dream-only Scenario profile，独立 commit。
2. Control v2、schema 可推进性与兼容 parser，独立 commit。
3. Progress audit、Dream operations UI、i18n、文档，独立 commit。

任何一步若必须改 Reality Character/Prompt 行为，应停下重新出设计，不得在本 Brief 内顺手扩大范围。
