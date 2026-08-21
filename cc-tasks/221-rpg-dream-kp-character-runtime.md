# Brief 221：跑团 KP / 角色卡双视图回合编排

> 状态：`blocked-by-220`
>
> 前置：Brief 219、220 已完成并各自独立提交
>
> 后续：Brief 222

## 一、目标

接通可玩的后端回合：用户可从角色栏或 KP 栏输入；纯旁白 KP 生成结构化裁定提案；Brief 220 内核决定结果并投影；现有角色卡驱动的 AI 角色只读取角色可见事件后自然回应。

角色仍是 PresenceKit 的 active AI 角色，不是 RPG engine 生成的普通 NPC。KP 不具人格，不替角色写台词。

## 二、开工前必读

- Brief 219/220 的代码、提交与测试结果
- `docs/rpg-dream-mode-design.md`
- `docs/dream.md`
- `docs/prompt-layers.md`
- `docs/model-presets.md`
- `docs/tools.md`
- `docs/runtime-lifecycle.md`
- `docs/interaction-event-model.md`
- `docs/security_model.md`
- `docs/dev-environment.md`

## 三、模型路由与 Prompt 边界

新增独立 routing profile `rpg_kp`，默认兼容回退 `intent -> chat`，使用短 timeout、零 SDK retry。同步 model registry、设置 effective state、`docs/model-presets.md` 与 `docs/feature-control-surface.md`；管理面不必新增单独选择器，但必须能在模型路由页看到/配置该 profile。

KP prompt 只包含：当前剧本/阶段的 KP 完整视图、当前 branch 世界快照、用户本轮输入、相关事件尾部、固定裁定 schema。不得包含 Reality memory、hidden state、afterglow、普通工具结果或角色私密 Reality prompt。

角色生成使用独立 `RpgCharacterView`，显式加载当前 active 角色卡及 RPG character projection。只允许角色可见的 public/character facts、当前用户公开行动和有限 transcript；不得注入 KP/private/player-only projection、骰点 seed/DC、未来 stage 或 Reality 记忆链。不得热切换全局 active character。

## 四、`<C>` 最小控制协议

角色侧不接普通 `_TOOL_REGISTRY`，也不启用现有 function-calling tool loop。实现专用纯解析器：

```text
<C>我想要观察周围</C>
```

契约：

- 只接受大写 `C`、单个标记、单行自然语言正文；去首尾空白后长度 2..120。
- 推荐正文以“我想要”或“我需要”开头，但解析器不依赖具体中文关键词判断权限。
- 标记必须从用户可见角色回复、transcript、archive、TTS/WS payload 前剥离。
- 未闭合、嵌套、重复、未知标签、超长内容全部不执行；作为普通文本保留或按现有安全渲染转义，并记 metadata-only 观测。
- 解析结果只是 `CharacterCheckRequest(intent_text)`，不携带技能、骰式、DC、修正或 visibility。

角色请求交给同一 KP proposal + deterministic engine；KP 可返回 `automatic_success/automatic_failure/roll/reject`。每个主回合最多处理一个角色请求，最多生成一次角色补充回应；补充回应中的新 `<C>` 只剥离并标记 `deferred`，不能递归执行。

## 五、公平且有界的 KP 调用

KP 在不知道骰面的情况下，一次提交裁定和全部结果分支；后端验证 proposal 后才掷骰并选择分支。禁止先把骰点给 KP、再让 KP决定 DC 或成功条件。

单主回合 LLM 调用硬上限：

```text
1 次用户行动 KP proposal
1 次主要角色生成（若 character_should_respond）
1 次角色 <C> 的 KP proposal（可选）
1 次角色补充生成（可选）
= 最多 4 次
```

无有效 `<C>` 时最多 2 次。validator/provider 失败不得用自由文本猜裁定；KP 失败时整轮 `failed` 且不应用未验证事实。角色失败可保留已提交的 KP/世界事件，并返回 `character_generation_failed` 的明确部分完成状态，下轮可继续。

## 六、回合 API

新增 typed endpoint：

### `POST /dream/rpg/turn`（`activity`）

请求：

```json
{
  "dream_id":"...",
  "request_id":"客户端生成的幂等 ID",
  "lane":"character|kp",
  "message":"...",
  "expected_scene_revision":3
}
```

服务端固定 owner/char/mode。`lane=character` 表示用户行动对角色可见；`lane=kp` 表示玩家秘密行动/规则询问，原文不得进入角色视图。

响应：

```json
{
  "dream_id":"...",
  "round_id":"...",
  "request_id":"...",
  "status":"completed|partial|failed",
  "scene_revision":4,
  "entries":[
    {"entry_id":"...","lane":"character|kp|shared","kind":"...","content":"...","ts":"...","correlation_id":"..."}
  ],
  "character_reply_generated":true,
  "dice_roll_ids":["..."],
  "error":null
}
```

响应只含玩家可见投影。KP internal prompt、隐藏 facts、seed、未选中的 outcome branches 不返回。相同 `request_id + digest` 返回原结果；相同 ID 不同内容返回 409 `RPG_IDEMPOTENCY_CONFLICT`。同一梦只允许一个 in-flight round，第二个请求返回 409 `RPG_ROUND_BUSY`。

## 七、回合顺序

```text
validate session/revision/idempotency
  -> append user action (按 lane 投影)
  -> KP proposal (看不到骰点)
  -> deterministic apply / dice
  -> append KP/shared entries
  -> optional RpgCharacterView generation
  -> strip optional <C>
  -> optional one bounded character-check subcycle
  -> commit round terminal status
```

整个关键区使用 owner conversation lock；任何网络/LLM 调用的 timeout、取消和终态必须可恢复。不得广播到 QQ/mobile/普通 desktop chat，不调用 `record_assistant_turn`、Reality turn sink、scheduler 或 ordinary tool loop。

## 八、测试

至少覆盖：

1. character/kp 两 lane 输入分别投影，KP 秘密原文不进角色 prompt。
2. 角色 prompt 确实由 active 角色卡驱动，且不包含 KP private/player-only/future stage/Reality memory。
3. KP 是纯裁判 schema，不输出角色台词；proposal 在骰点前冻结。
4. auto success/failure/reject 与 roll 均能驱动角色可见事件。
5. `<C>` 正常、缺失、未知、重复、嵌套、超长、正文为空；用户可见输出无控制标签。
6. `<C>` 最多一轮一次，补充回复不递归，LLM 调用硬上限成立。
7. KP validator/provider 失败零事实提交；角色失败形成可恢复 partial。
8. request id 幂等、digest 冲突、revision conflict、round busy、timeout 和取消。
9. 用户从任一 lane 都能触发 KP 自动推进并得到可选角色回应。
10. Reality sink/memory/tools/stimulus/channel broadcast 零调用。
11. `rpg_kp` routing profile、fallback、timeout 与 API call ledger caller 可观测。

```powershell
pytest -n auto tests/test_dream_rpg_runtime.py tests/test_dream_rpg_character_marker.py tests/test_dream_rpg_prompt_isolation.py tests/test_dream_rpg_engine.py tests/test_model_registry.py tests/test_api_call_log.py tests/test_dream_isolation_guard.py
```

## 九、文档与闭环

同步 `docs/dream.md`、`docs/model-presets.md`、`docs/feature-control-surface.md`、`docs/tools.md`、`docs/three-repo-interface-catalog.md`。客户端仍标 `open`，不在本单修改 Emerald-client 或 mobile。

## 十、验收与提交

可通过 HTTP 完成双 lane 跑团回合；角色卡身份、知识隔离、公平骰点和调用预算均由测试证明。完成差异检查后立即创建独立 Git commit，再开始 Brief 222。

