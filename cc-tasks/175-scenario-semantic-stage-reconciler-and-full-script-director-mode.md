# Brief 175：Scenario 语义阶段校准、全量剧本导演模式与独立模型路由

## 背景与现场结论

Brief 169 已把 Scenario 主 Prompt 改为专用 profile，并把阶段控制收敛为短 ID：

```text
<scenario_control>{"hit":["E1"],"blocked":[]}</scenario_control>
```

但真实运行中仍出现同一 stage 连续 20 轮 `control_missing`、`stall_turns=20`。可见剧情可能已经自然进入下一阶段，
后端却因为主模型没有输出控制块而一直停留在旧 stage。继续增加主回复必须填写的字段或强化提示，不能解决模型长期忽略
机器控制尾注的问题。

本 Brief 增加两条互补能力：

1. 在控制块缺失/无效或持续停滞时，**额外调用一次独立模型 API** 做语义阶段校准；
2. 提供显式可勾选的“全量剧本导演视图”，让主模型看到完整有序剧本并按上下文自然演出。

语义校准是兜底裁判，不替代现有确定性 `scenario_control` 快路径；全量注入是实验性 opt-in，不改变默认严格分阶段行为。

## 已决定的产品边界

1. 默认模式仍是 `strict_stage`：主模型只看到当前 stage，现有用户不迁移、不静默改变行为。
2. 新模式为 `full_script`：开关放在“后端管理面板 → 梦境设定 → 剧本设定”，默认关闭。
3. 设置通过现有 `GET/PATCH /dream/settings` 持久化，只在进入梦境时冻结；进行中的梦不因管理面改动而热切换。
4. 语义校准确实是一次新的 LLM/API 调用，但只在满足触发条件时执行；同一 assistant turn 最多发起一次，不是无条件给每轮
   翻倍调用。
5. 校准调用必须在可见回复已经返回/发送之后异步执行，不得增加当轮首字或完整回复延迟。
6. 校准器只能判断 `stay | advance_next | uncertain`；最多顺序前进一个 stage，不能选择任意 stage、跳关或回退。
7. 现有合法 `scenario_control` 仍由 Python 同步确定性裁决，不能为了接入校准器把成功路径改成第二次 LLM 裁决。
8. 新调用使用独立 `call_category=scenario_reconcile`，在管理面的“模型路由”页面可为每个 routing profile 单独指定 preset。
9. Dream 仍是玩法之一：不得修改 Reality chat 的角色卡字段、Prompt 层、模型路由选择或普通聊天延迟。

## 范围 A：梦境设定中的全量剧本开关

### 设置合同

在 per-uid Dream settings 增加枚举字段：

```yaml
scenario_injection_mode: strict_stage  # strict_stage | full_script
```

- `strict_stage` 为默认值和 legacy settings 的兼容回退。
- `PATCH /dream/settings` 只接受上述两个值，未知值返回 422，不写入部分脏状态。
- `/dream/enter` 把该值冻结进本场 Dream state；`GET /dream/state` 返回实际冻结值，而不是当前偏好值。
- active dream 期间修改设置只影响下一场，和现有 `world_layer` / `lucid_mode` 合同一致。
- Sandbox、Mirror、Group Dream 不消费该字段；本 Brief 不把单人 Scenario 设置误接到群聊 Dream Stage。

### 管理面

在“梦境设定 → 剧本设定”增加可勾选项“全量剧本导演视图（实验性）”：

- 未勾选对应 `strict_stage`，勾选对应 `full_script`；
- 明确说明“下一场梦生效”；进行中的梦显示“本场实际模式”与“下场偏好”，避免用户以为已热切换；
- 中文说明风险：额外 token、后续阶段剧透、模型注意力分散；
- 同时说明后端仍按阶段顺序推进，勾选不等于允许跳关；
- 文案、错误、状态均有完整中英文 i18n；不能只在中文 HTML 写死；
- 修改 page fragment 后按工程规则更新 `ADMIN_UI_FRAGMENT_VERSION`、`core.js?v=`；修改直载 JS/CSS 时同步对应 `?v=`。

开关属于 Dream 设置，不写进角色卡，不写进单个 scenario YAML；同一剧本可以分别用严格模式和全量模式做对照。

## 范围 B：全量剧本导演投影

### 严格模式

`strict_stage` 保持 Brief 169 的 Scenario Prompt profile 和 DS 当前阶段投影，不额外注入下一阶段或完整剧本，作为行为基线。

### 全量模式

`full_script` 在 Dream-only DS 投影中向主模型提供有序的完整剧本导演视图：

- script 标题/作者可见说明；
- 全部 stage 的稳定 ID、名称、`dramatic_task`、`entry_pressure`、`exit_signs`、`not_yet_allowed` 与 stage 级
  `drift_pressure`；
- scenario 顶层 private truths 及现有 disclosure policy，保持“角色可知、按阶段披露”的语义；
- 最醒目的后端权威标记：当前 stage ID、当前 stage 序号以及“可演到下一阶段，但不得自行声明跳过中间阶段”；
- 当前 stage 的 E/B 短 ID 控制合同仍保留，作为无需额外 API 的确定性快路径。

该投影必须由 Dream-only 纯函数生成，不修改 authored YAML、不原地 mutate `Scenario`/`Character`，也不得重新引入被 Scenario
profile 排除的 Sandbox/Reality 层。Prompt inspector 显示 `scenario_injection_mode`、投影版本、stage 数量和估算字符/token；不展示
未授权的私密正文给普通 state.read 页面。

### 大剧本预算

- 在保存/导入剧本以及进入 `full_script` 梦境前计算可解释的规模估算；
- 超出明确上限时拒绝启用/进入并返回可操作错误（stage 数量、估算 token、上限），不得静默截断后续 stage；
- `strict_stage` 仍可运行同一大剧本，不能因全量模式预算问题把剧本整体判坏；
- 不通过删掉 exit signs、约束或 private truth 来伪装成“全量注入”。

## 范围 C：异步语义阶段校准器

### 触发条件

单人 Scenario assistant turn 完成主回复与现有控制裁决后，满足以下任一条件才排队一次校准：

- `scenario_control` 为 `missing` 或 `invalid`，且当前 stage 尚非最后阶段；
- 控制块合法但连续停滞达到配置的保守阈值（默认建议 `stall_turns >= 2`）；
- `full_script` 模式中主模型未给出合法当前-stage hit，需要同步“叙事事实上是否已进入下一阶段”。

若合法控制块已完成推进/结局、Dream 已退出、不是 Scenario、没有下一 stage，则不得调用。相同
`dream_id + assistant_turn_id + from_stage_id` 用幂等键去重，进程内重试或重复 sink 不得产生多次账单。

### 输入与输出

校准 Prompt 只提供判断所需的最小上下文：

- 当前 stage 的任务、进入压力、完成信号和禁止提前发生事项；
- 紧邻的下一 stage 的任务与进入状态；
- 最近有界的用户/角色可见对话片段；
- 明确的反例规则：提及、假设、否定、威胁、计划或旁白预告不等于事件已经发生。

不发送完整角色卡、Reality memory、其他后续 stage、工具 schema 或管理面密钥。输出合同保持最小：

```json
{"decision":"stay"}
```

`decision` 仅允许 `stay | advance_next | uncertain`。不要求模型照抄 exit sign、不要求输出长解释、不接受 `next_stage_id`，
也不从自由文本猜测决定。解析失败等价 `uncertain`。

### 异步应用与竞态

- 调用走 `core.llm_client`，显式传 `call_category="scenario_reconcile"` 与当前 `char_id`，从而遵守角色卡
  `presence_ext.model_routing` 优先于全局 `active_routing` 的既有合同。
- 调用必须在回复发出后由受管后台任务执行；不得在 send/HTTP response 前 await 网络。
- 排队时捕获 `dream_id`、`from_stage_id`、`state_version`、`assistant_turn_id`。返回时仅当四者仍匹配且 Dream 仍 active 才可应用。
- `advance_next` 只调用现有顺序推进 primitive，并以 compare-and-set/等价原子保护最多推进一阶段；不得另写一套 stage 状态机。
- 若用户已开始下一轮、已有确定性推进、退出/重进梦境或 state version 改变，结果标记 `stale` 并丢弃，不追赶、不补跳。
- `stay` 和 `uncertain` 不改 stage；上游超时、限流、解析错误、路由错误均 fail-open，不影响可见回复、Dream history 和 hard exit。
- 后台任务必须有并发上限、短 timeout 和可测试的 shutdown/cancellation 收口；不允许每轮无限堆积。

语义校准只纠正“叙事已进入紧邻下一阶段但控制块没跟上”的状态差，不做通用剧情评价、内容审查、关键词扫描或 embedding
相似度判定。

## 范围 D：管理面模型路由

### 路由类别

新增正式 routing category：

```yaml
scenario_reconcile: <preset-name>
```

- `config.example.yaml` 的每个示例 routing profile 展示该 category；推荐指向稳定的轻量模型。
- 为兼容旧 profile，解析回退顺序固定为
  `scenario_reconcile → intent → chat → first preset`，并用 focused test 固化；不能悄悄只回退主 `chat` 导致费用突增。
- category 仍服从 per-character routing profile 覆盖；不得新增一个绕开 `model_registry` 的独立 base URL/API key 配置。
- preset rename/delete/reference 校验必须把任意 category 映射一视同仁，确认新增 category 不被 UI 白名单或 schema 丢弃。
- 调用进入现有 API call ledger，`purpose=scenario_reconcile`，以便统计次数、延迟、失败与成本边界；不记录 Prompt/对话正文。

### 管理面模型路由页面

在 Routing Profile 新建/编辑 UI 的 category 列表加入 `scenario_reconcile`：

- 中英文释义为“Dream Scenario 阶段语义校准；仅在控制缺失/无效或持续停滞时额外调用”；
- preset 下拉、已保存映射 chips、读取回填、更新请求均支持该字段；
- 页面显示所选 profile 下该 category 的“显式 preset”以及按上述回退链计算的“实际生效 preset/来源”；
- 活跃角色固定 routing profile 时，继续显示角色覆盖告警，并能看到该 profile 的
  `scenario_reconcile` 实际 preset，而不是只显示 `chat`；
- legacy 合成模式、只配置 `chat` 的旧 profile 和缺失 `intent` 的 profile 都有明确、可预测显示；
- 不显示 API key，不能用“发起一次真实校准”作为页面加载或读取生效值的方式。

同步更新 `docs/model-presets.md`、`docs/feature-control-surface.md` 与管理面 i18n/static cache。桌面端
`/settings/model-routing` 仍只切整套 profile；本 Brief 不在桌面设置页新增单 category 选择器。

## 范围 E：梦境运维观测

扩展 Brief 169 已有有界 `scenario_progress_audit`，并在“后端管理面板 → 观测 → 梦境运维”的剧本推进卡展示：

- frozen `scenario_injection_mode`；
- reconciler trigger：`control_missing | control_invalid | stalled | full_script_sync`；
- 请求状态：`queued | running | completed | failed | stale | cancelled`；
- 安全路由信息：effective profile、preset 名、provider/model 标识（沿用 API call ledger 的脱敏策略）；
- decision：`stay | advance_next | uncertain`；
- applied、from/to stage ID、state version 匹配结果、耗时和安全 failure code；
- 本场触发次数、应用次数、stale 次数和失败次数。

不得记录用户输入、角色回复、剧本正文、private truth、完整 Prompt、API key、base URL credential 或模型自由文本解释。若沿用
现有同一 ledger，保持最近 200 条有界 retention；若新增落盘物，必须经 `core.data_paths` 定位、原子写入并同单提供只读端点。
审计写入失败 fail-open。

梦境运维需要让用户能直接区分：

- 主模型 control 已推进（没有额外调用）；
- 校准器认为仍在当前阶段；
- 校准器建议推进且已应用；
- 校准结果因竞态过期被丢弃；
- 校准 API 未调用或调用失败。

## 配置、文档与兼容

- `scenario_injection_mode` 缺失时按 `strict_stage`；不批量迁移用户 settings 或运行中 Dream state。
- 旧 archive/state 可读；缺失 reconciler 字段时管理面展示“未启用/无记录”，不报错。
- 新 timeout/并发/停滞阈值若可配置，使用 Dream 专属后端配置并在管理面只读显示最终值；不要让普通用户承担一组难懂调参。
- 更新 `docs/dream.md`、`docs/prompt-layers.md`、`docs/model-presets.md`、`docs/feature-control-surface.md`、
  `docs/data-taxonomy.md` 和必要的 runtime/operations 文档。
- 若施工触及 runtime task owner 或 shutdown 生命周期，先按 AGENTS.md 补读 `docs/runtime-lifecycle.md`、
  `docs/interaction-event-model.md`、`docs/security_model.md`。

## 不在范围内

- 不修改 Reality `core/prompt_builder.py`、Character 顶层字段、普通 chat、scheduler 主动消息、growth 或 activity Prompt。
- 不把全量剧本模式设为默认，不让模型任意选 stage，不实现分支图/回退/多 stage 跳转。
- 不删除 Brief 169 control v2，不恢复要求模型输出整段 exit sign 的旧重合同。
- 不用关键词、正则或 embedding 直接判定剧情完成；它们无法可靠处理否定、假设、转述和语义等价。
- 不在校准调用里暴露 Reality memory、Dream hidden state、用户隐私快照或未授权工具。
- 不改变 hard exit、自动回到 Reality chat 与梦醒消息闭环；该合同由 Brief 170 维护。
- 不修改 Scenario YAML/JSON 导入导出格式、回放渲染或角色卡 Scenario identity；分别由既有 Brief 负责。
- 不为本功能新建另一套 provider SDK、API ledger、路由系统或管理面顶级页面。

## 预计主要文件

- `core/dream/dream_settings.py`
- `core/dream/dream_prompt.py`
- `core/dream/dream_pipeline.py`
- `core/dream/scenario_core.py` / 现有顺序推进 primitive
- 新的 Dream-only semantic reconciler 模块
- `core/dream/scenario_progress_audit.py`
- `core/model_registry.py`
- `core/llm_client.py`（仅 timeout/category 接线，不复制出口）
- `config.example.yaml`
- `admin/routers/dream.py`
- `admin/routers/settings_llm.py`（仅需 effective category 投影时）
- `admin/static/pages/dream-settings.html`
- `admin/static/js/dream-settings.js`
- `admin/static/pages/model-routing.html`
- `admin/static/js/settings.js`
- `admin/static/pages/observe-dream-operations.html`
- `admin/static/js/dream-operations.js`
- `admin/static/i18n.js` 及缓存版本 owner
- `docs/dream.md`
- `docs/prompt-layers.md`
- `docs/model-presets.md`
- `docs/feature-control-surface.md`
- `docs/data-taxonomy.md`
- focused Dream/model-routing/admin tests

## 验收标准

1. 未设置新字段的用户与 legacy state 始终是 `strict_stage`；Sandbox、Mirror、Group Dream 和 Reality chat Prompt 逐层无回归。
2. 管理面 Dream settings 可保存/回读全量剧本复选框，并清楚显示“下一场偏好”与 active dream 冻结值；中英文和缓存版本正确。
3. `full_script` Prompt 含所有有序 stage、后端权威当前 stage 和现有控制 v2；`strict_stage` 不泄漏后续 stage。
4. 超预算剧本在 full mode 被明确拒绝且 strict mode 仍可用；没有静默裁剪、半截剧本或 authored 文件改写。
5. 主回复缺失/非法 control 或达到停滞阈值时，每个 assistant turn 最多产生一次
   `scenario_reconcile` API 调用；合法 control 已推进时零额外调用。
6. 人物只是威胁、计划、否定或假设下一阶段事件时，校准器返回 `stay/uncertain` 不推进；叙事已实际进入紧邻下一阶段时
   `advance_next` 最多推进一阶段。
7. 人工延迟校准响应时，可见回复先返回；状态版本变化、下一轮已开始、Dream exit/re-enter 后的旧结果全部标记 stale 且不应用。
8. 上游 timeout、429、异常 JSON、未知 enum、审计写失败均 fail-open，不吞回复、不损坏 state、不触发跳关。
9. 管理面模型路由可配置并回读 `scenario_reconcile`，能展示显式/回退后的实际 preset；旧 profile 按
   `intent → chat → first preset` 兼容。
10. per-character profile 覆盖、全局 active profile、preset rename/delete、legacy 合成模式均正确处理新 category；Reality `chat`
    的解析结果不变。
11. API call ledger 与 Dream operations 能回答“是否调了额外 API、走哪个安全路由、决定是什么、是否应用/过期/失败”，且不含正文。
12. 连续 20 次 control missing 的回归夹具不再无限卡住：当夹具叙事已经进入下一 stage 时校准器推进；未进入时保持并持续可观测。

## 验证

- Dream settings/API：默认值、枚举 422、局部 PATCH、active dream 冻结、下一场生效、旧 state 回读。
- Prompt fixture：strict/full 投影矩阵、完整顺序、当前 stage 标记、private truth disclosure、预算拒绝、Scenario profile 隔离。
- Reconciler focused tests：触发/不触发、每 turn 幂等、最小 JSON parser、否定/假设 fixture、只推进下一阶段、last-stage no-op。
- 并发测试：延迟返回、state CAS、下一 turn、确定性控制抢先推进、exit/re-enter、取消/shutdown、并发上限。
- Model routing tests：`scenario_reconcile → intent → chat → first preset`、char override、global profile、rename/delete/reference、legacy synth、
  API call purpose。
- Admin tests：Dream setting checkbox、Model Routing category/effective source、Dream Operations safe projection、scope、i18n key、静态缓存版本。
- `pytest -n auto` 运行上述 focused suites；仅当实际触及 tag 规则时再运行 `python tests/run_eval.py`。
- `py_compile`、`node --check`、`git diff --check`；真实浏览器目检三处管理面。未做真实浏览器目检时管理面验收标记 partial。
- 人工/集成 smoke 使用脱敏剧本分别验证 strict 与 full 模式；模拟慢校准 API，证明当前可见回复不等待第二次调用。
- 确认没有修改真实 `userdata/` 剧本、角色卡、`data/runtime` 或生产 Dream settings。

## 建议施工顺序与独立提交边界

1. Dream setting + 管理面复选框 + frozen state/API/兼容测试，独立 commit。
2. full-script Dream-only 投影、预算守卫、inspector 与 Prompt tests，独立 commit。
3. semantic reconciler 的最小调用、异步任务/CAS/幂等与 focused tests，独立 commit。
4. `scenario_reconcile` 路由 fallback、示例配置、Model Routing UI/effective projection 与文档，独立 commit。
5. progress audit、Dream Operations 聚合/i18n 与故障/竞态测试，独立 commit。
6. strict/full 集成 smoke、延迟 API 证据、Reality/Sandbox/Mirror/Group 回归与文档收口，独立 commit。

每一步相关测试和差异检查完成后立即提交。若无法证明异步调用不阻塞当轮回复、旧结果不会错推新 state，或 Reality chat 路由
未受影响，则该 Brief 只能标记 `partial`，不得以单元测试数量代替合同验收。
