# docs/known-issues.md — 已知问题与技术债

> 最近核对：2026-07-16（cc-tasks/28 三仓技术债清盘）。
> 这里只保留仍需行动或观察的条目；已关闭条目的完整背景保留在 Git 历史。

## 当前仍存在

### PROF-1：user_profile 场景类字段的反抖动阈值曾经"锁死"（已修复 2026-07-25）

**状态**：`closed`（记录于此供以后同类字段参考，不是待办）

`core/memory/user_profile.py::update()` 的 pending-override 反抖动机制默认要求同一
新值被"连续 2 次一致提取"才落盘覆盖，本意是防止单次幻觉提取翻转已确认的值。但
`location` 这类"此刻状态"字段用户通常只提一次（"我现在在绍兴"），`extract_and_update`
每次只喂最近 10 条用户发言，话题一岔开就再也凑不出第二次一致提取，`location` 从此
追不上现实——连带天气工具跟着一直查旧城市（`main.py` 把 `profile['location']` 当天气
查询的默认城市）。已加 `_PENDING_OVERRIDE_THRESHOLD_BY_FIELD`，`location` 单独降为
阈值 1，其余字段（name/pets/interests/occupation）保持阈值 2。同时修了 `main.py` 里
`profile.get("location", "杭州")` 的经典 dict.get 语义坑（key 存在但值为 None 时不
会触发 default，改用 `profile.get("location") or "杭州"`）。回归见
`tests/test_user_profile_override.py`（8/8b 用例）、`tests/test_profile_location_fallback.py`。

若未来再给某个"易变但用户通常只说一次"的字段加反抖动保护，请复用
`_PENDING_OVERRIDE_THRESHOLD_BY_FIELD`，不要照抄默认阈值 2。

### GROUP-1：跨角色印象摘要语气曾无约束、易读出暧昧色彩（已修复 2026-07-25）

**状态**：`closed`

`core/stage/char_relations.py::_relation_prompt()` 生成的角色间"第三人称印象"摘要
会被 `core/stage/context.py::render_presence()` 原样当作既有事实注入每一轮群聊
prompt（无 tag 门控、无相关性判断，roster 里任意两个角色只要有过互动就会被注入）。
旧 prompt 对措辞语气没有约束，LLM 生成摘要时容易往暧昧/亲密方向靠，角色会把这段
"既有印象"当真，没来由地说出"今晚我跟{另一角色}聊天的时候……"这类话（茶茶反馈）。
已给 `_relation_prompt()` 加中性克制的措辞约束。这是内容侧修复；`render_presence()`
本身"每轮无条件注入所有已知关系"的设计没有改动——这是群聊"在场感"功能故意要的
效果（让角色记得彼此），如果以后还想加相关性门控（比如只在话题涉及对方时才注入），
需要专门评估，不在这次修复范围内。

### TRACE-1：recall trace 三元组解包报错（已修复 2026-07-25）

**状态**：`closed`

`core/pipeline.py::fetch_context()` 拼 recall trace 字典时，`semantic_hits` 那行按
`for _sid, _dist in _semantic_hits` 二元解包，但 `core/memory/vector_store.py::
query_async()` 返回的是 `(source_id, distance, ts)` 三元组，线上天天报
`"[pipeline.fetch_context] recall trace write failed: too many values to unpack
(expected 2, got 3)"`（茶茶反馈实际日志）。已改用下标取值（`h[0], h[1]`），与旁边
debug log 那行一直用的写法一致。回归见 `tests/test_recall_trace.py::
TestFetchContextSemanticHitsTraceUnpack`。

### PB4：Path B 降级观察期

**状态**：`observe`
**到期倒计时**：2026-08-10 到期。到期无缺口记录就开删除 brief。

`config.intent_reflex.enabled` 默认关闭，旧 Path B 守卫暂留。观察期若出现 tool loop 已启用但“角色说了要做却没做”的用户可感缺口，在此登记触发消息、期望动作和实际结果；到期仍无记录则整删 `_parse_and_execute_intent`、守卫、幂等窗口及对应测试。

**2026-07-25 更新**：此前最大的缺口——`dream_invite` / `toy_invite` 只经 Path B 触发、
未注册进 `_TOOL_REGISTRY`（`cc-tasks/103` 点名的最大风险点）——已迁移补齐，两者现为
`desktop` 类目正式工具，Path A/C 均可触发（见 `docs/tools.md` 意图解析节 2026-07-25 迁移
说明）。至此 Path B 支持的 7 种意图全部有 Path C 同款覆盖，103 号删除单不再有已知阻塞项。
仍需真机做一次冒烟（危险模式窗口内触发一次 desktop 类动作 + toy_invite/dream_invite，确认
均由 tool loop 正常执行）后再确认到期删除。

**2026-07-25 追加发现并已修复**：排查 API 契约测试（见下方新增观测面板）时发现 Path B
剩余 3 种意图（`send_notification`/`play_pause`/`play_song`）推送的 `type` 字符串与前端
`ws.ts::_dispatchAction` 实际认识的 `show_notify`/`media_play_pause`/`play_netease`（+
`song_id` 而非 `song_name`/`artist`）从不一致——这 3 种意图经 Path B 触发时从未真正生效
过，只是一直被优先生效的 Path C 同名正确实现掩盖。已在 `core/pipeline.py` 对齐（
`_INTENT_ACTION_TYPE_MAP` 做 type 翻译，`play_song` 改为委托 `_play_song_wrapper` 复用
网易云搜索解析），回归测试见 `tests/test_intent_grounding.py`。结论不变：Path B 的用户可
感能力 Path C 全部覆盖，且已验证正确，103 号删除单依旧无阻塞项——这次修复只是让 Path B
在被删除前的观察期内也是"真的能用"的，而不是名义上支持、实际从未生效。

**2026-07-25 新增工具**：管理面板「观测」区新增三块面板，供日常自查：
- `GET /observability/resource-completeness`（`core/resource_completeness.py`）——扫描
  各功能开关/素材配置状态，标出"关着"和"开了但缺素材"；附一份人工维护的"功能压根还没
  做"清单（当前含移动端 TTS 投递、桌宠语音条 UI 解耦、Live2D/3D 绑定前端消费三项，来源
  见 `cc-tasks/124`/`125`/`docs/tools.md`）。
- `GET /observability/api-contract-check`（`core/api_contract_check.py`）——扫后端
  `_push_desktop_action` 产出的 type 字符串 + Path B 意图翻译表，和前端 `ws.ts` 的
  `_dispatchAction` switch 取差集，就是上面这次漂移的检测器。前端仓库不存在时优雅跳过
  （约定与本仓同级目录，或设 `EMERALD_CLIENT_REPO` 环境变量）。
- `GET /observability/character-permissions` + `POST .../test`（
  `core/character_permissions.py`）——按类目（info/desktop/memory/system/fs/
  phone_control）列出对某角色的暴露面、是否受危险模式闸门约束，以及身份固化管线
  （角色自己改 identity.yaml 那条后台链路）的状态；测试按钮对 identity_consolidation/
  fs 两条安全链路真实执行一次，其余会产生真实副作用的类目（弹通知/震动/关机等）只做
  就绪检查清单，不会代用户触发。

### ACT-1：阅读动向跨角色串桶

**状态**：`observe`（前端已分桶，待复现观察）
**位置**：后端 activity 路径；前端 `SubFlow.tsx`

后端已确认按 `char_id + uid` 隔离且无角色默认参数。PresenceKit-desktop 已于 2026-07-16 将时间轴改为 `subflow_timeline:{charId}`，旧全局桶一次性迁入当时激活角色并删除。若仍复现，再核对操作时的 `active_character` 与后端请求。

### ACT-2：反坍缩重试未覆盖流式路径

**状态**：`observe`（方案 B 已落地，观察单轮坍缩率）
**位置**：`core/pipeline.py::Pipeline.run_llm_stream()` / `Pipeline._check_stream_collapse()`

`cc-tasks/105` 已裁决并实现方案 B——流式路径不丢弃重试（暂缓前 N token 的方案 A 已封存），
命中句首同质坍缩（S2 同源检测）时只记观测日志（`[anti_collapse] stream_soft_degrade`）+ 写入
下一轮一次性信号，由下一轮 `build_prompt` 注入 `stream_collapse_hint` 层纠偏，详见
`docs/prompt-layers.md` §反坍缩治理 · ACT-2。**观察项**：若上线后单轮内坍缩率（同一条流式回复
内部即出现重复句首，而非跨轮）显著高于非流式路径，需复议启用方案 A。

### F8：管理面板对话 UI 右键历史未实现

**状态**：`post-v0.1`
**位置**：`admin/static/index.html`

不影响主链路。需要时另开管理面体验工单，不在后端技术债清盘中扩张范围。

### DREAM-1：身份稳定性测试仍是弱代理

**状态**：`observe`

人称与依恋关键词只提供最低限度信号；`GET /dream/invariants` 已补跨梦矛盾观测。继续以实际游玩和 identity eval 双轨观察。

### identity-2：identity 注入有冷启动期

**状态**：`observe`

新用户需经过 mid-term → episodic → consolidate 才开始注入。先观察首个有效维度需要的轮数，再决定是否调阈值。

Brief 104 §3 已落地两块基础设施，供后续判断：
- **量化**：`consolidate_to_identity()` 检测到某用户首次出现 confidence>=0.5 的维度时，
  记一条 `identity_coldstart` 日志到 `fixation.jsonl`（真实轮数取自
  `event_log.count_real_turns()`，即 full_log.md 里 `speaker:user` 计数，不受
  short_term 20 轮滑窗影响）。跨用户汇总见
  `GET /memory/fixation/identity-coldstart-summary`；单用户明细见
  `GET /memory/fixation/status?uid=...`。
- **降级体验**：`user_identity_text` 为空但已有真实交互历史（复用
  `core/scheduler/rhythm.has_real_interaction_history()` 同一冷启动阈值）时，注入
  `6a_user_identity_coldstart` 层，如实表达"还在慢慢认识你"，不编造记忆内容（详见
  `docs/prompt-layers.md`）。
- 积累到有意义的样本量后，再回来看 `avg_real_turns` 决定是否调
  `_should_consolidate()` 的阈值。

### TD-1：`sandbox.py` 兼容层

**状态**：`observe`

`core/data_paths.py` 已承接实现，但大量调用与测试 fixture 仍依赖 `core.sandbox.get_paths()`。当前把它当稳定兼容层，不为命名整洁做大范围替换。

### Brief 28/29 运行观察

**状态**：`observe`

- tool loop 与 QQ 关键词快速路径理论上可能在同轮重复执行幂等工具；出现有副作用的快速路径前重新评估。
- MCP 工具描述和结果是不可信输入；v1 只有截断和来源边界，后续需要时按 web 召回同级做内容隔离。

## design-backlog

**2026-07-16 全部拍板关闭**，裁决与理由见 `DESIGN.md` §十一（决策 3–8）。摘要：

- D7：**不回流**（自产内容不固化原则）。
- G4：**最小方案**，全落 `storage.json` history；gift 可触发一次性主动消息（走 ledger）。
- DESIGN-1：**默认只影响态度**，直说需 tag 命中 / 健康告警 / 用户显式问三者之一。
- DESIGN-2：**追认现状三级**（健康可打断 / 情感 QUIET+ledger / 信息可 defer）。
- SC1：**维持冻结**。
- REC1：**observe**，出现实际坏召回样本再动。
- PB1：**并入决策 1**（数据级来源标记原则，Brief 79 模式），召回链复评时执行。

需要写码的两条（G4 最小方案、P2-1）已各自出单落地（Brief 83 / Brief 82），见「本轮已核对关闭」。
其余为纯设计裁决无代码工作。

## 用户动作（代码侧无事可做）

- SEC-AUTH-2 P4 后半：各持有方切换新 token；ESP32 重烧录；Watch Shortcut 与管理面板换值；全部确认后再轮换 legacy secret。
- `data/runtime/auth/audit.jsonl` 约 200 条 `ip=testclient` 测试噪音：由用户决定是否手动清空，本工单不删除数据。

## 本轮已核对关闭

| 编号 | 结论 |
|---|---|
| ADMIN-1 | `jailbreak_entries.py` 已导入 `pathlib.Path`。 |
| F11 | Brief 28/29 tool loop 默认 categories 已包含 `memory`，生成侧接线完成。 |
| P2 `_layer` | `llm_client.py` 在 provider 边界统一调用 `sanitize_messages()`。 |
| PB3 | episodic 加载 fail-loud；空列表覆写非空文件护栏、写后 JSON 校验和 `.bak` 均存在。 |
| TEST-1 | `test_sandbox_paths.py` 已断言 `runtime/channel_queue.json`，旧 `_identity_file` 全仓零命中。 |
| B11 / F10 / D2 / P1 / SEC-AUTH-1 / SEC-WS-1 / identity-1 / TD-2 / TD-3 | 均已完成，已从当前问题区移除。 |
| R6 final | 单出口稳态已完成（2026-06-11）：R1-D 后 QQ 路径完整接入 `turn_sink`，全部 LLM_ASSISTANT_REPLY 均经 scrub 链。守卫：`tests/test_r6c_reality_scrub_final.py`。 |
| PB2 | 2026-07-16 在 `1.5_fact_boundary` 加桌宠身份锚点；空屏幕感知时明确禁止虚构屏幕场景，并有专项测试。 |
| P2-1 | Brief 82：`tool_read_log.detect_bypass_intent()` 探测显式重读短语常量表，命中给本轮 `execute()` 传 `bypass_read_log=True`，`is_recently_read(bypass=True)` 放行拦截但指纹照常刷新。 |
| G4 | Brief 83：`garden_manager.daily_check()` 里 `dry`/`gift`/`ask` 处理完成后统一落 `storage.json.history`（`kind/flower/mood_source/ts/note`）并离开 `harvest`；`garden_handle_self` proposer 收窄为仅 vase，`ask`/`dry` 不再发消息，仅 gift 保留经 `ProactiveLedger` 记账的主动消息；`GET /garden/state` 新增 `history_recent`。 |
| H1 | Brief 88：`user_hidden_state` 现实侧写入链已全量接线——`RealityEventType` 扩至 5 类（新增 `BODY_TOPIC` / `AFFECTION_EXPRESSED`）；对话侧判定落在新模块 `core/memory/user_hidden_state_reality_signals.py`，挂 `pipeline.post_process_slow` detect_emotion 之后，trigger 轮零参与；`NO_INTERACTION` 挂现有 `hidden_state_decay` 12h tick，presence gap ≥24h 且逻辑日未记账时 accrue，去重 stamp 落盘于 `hidden_state_no_interaction_stamp.json`；`body_memory` 长期层经 `integrate_body_cue_and_save` 接线，仅在调用方 envelope.can_write_memory=True 时写入；`hidden_state_debug` 观测端点新增 `trigger_counts`。见 `cc-tasks/88-hidden_state现实侧接线-全量信号映射.md`；测试 `tests/test_hidden_state_reality_signals_brief88.py`。 |
| P3 | Brief 102：`build()` 强制裁剪后从最终 `messages` 按 `_layer`（含 `_report_layer` 覆盖）重算 `layers_activated`，新增 `layers_before_trim` 保留裁剪前全集；`_layers` 构建期累加器已删除。`6c_episodic` fallback 分支新增 `_report_layer="6c_episodic_fallback"`，保持与 `_layer` 共享消融规则的同时不破坏 memeval `layers_absent` 对"命中检索 vs 兜底注入"的区分。测试 `tests/test_prompt_trim_layers_recompute.py`。 |
