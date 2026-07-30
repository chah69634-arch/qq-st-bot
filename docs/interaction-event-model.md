# docs/interaction-event-model.md — Interaction / Event Envelope Model

> 状态：历史设计说明，已于 v0.2.2 preflight 复核。
> 本文记录三维 envelope 的词汇和现有边界，不是已发布的统一协议，也不是 v1 实现计划。代码为准；未实现设计保留在本文仅为历史/后续评估，不能作为客户端或后端的实现依据。

---

## 一、三维 Envelope

每个进入系统的交互事件由三个正交维度 + meta 字段描述：

### 1.1 Realm（世界层）

| 值 | 含义 |
|---|---|
| `reality` | 现实会话（正常陪伴 pipeline，写 short_term / memory） |
| `dream` | 梦境会话（独立 dream pipeline，不写现实记忆） |

两个 realm **完全隔离**：dream 事件不经过 reality gate，reality 事件不进入 dream pipeline。
realm 在入梦时由 `dream_state.status` 决定，是系统级属性，**不由事件本身声明**。

### 1.2 Kind（事件种类）

| 值 | 含义 | v0.1 状态 |
|---|---|---|
| `message` | 用户发送的文字/图片消息 | ✅ 已实现 |
| `stimulus` | 系统主动触发（定时器、传感器、desktop wake） | ✅ 已实现（代码名 `trigger`） |
| `tool` | 工具调用结果回注 | 未实现为独立 kind |
| `activity` | 活动会话生命周期事件 | 未实现为统一 event kind |

**v0.1 LLM 回复出口只产生 `message` 和 `stimulus` 两种 kind。** 任何 LLM 生成的结果通过 turn_sink 广播，不再以 event 形式回注系统。

### 1.3 Lifecycle（生命周期）

| 值 | 含义 |
|---|---|
| `oneshot` | 单次独立事件，不维持 session 状态 |
| `session` | 有明确开始/结束的会话（入梦/退梦、ActivitySession） |

当前 reality pipeline 的既有入口均按 `oneshot` 处理。dream 作为整体是一个 `session`，但 dream 内部每轮 dream_turn 也是 `oneshot`。Stage 是显式创建/关闭、由入口驱动的独立 `session`；它不经 `perceive_event`，也未接入统一 reality/dream event pipeline。ActivitySession 不在本模型的已实现范围。

---

## 二、Meta 字段

```python
# 概念字段（对应 PerceiveEvent dataclass + trigger audit log）
event_id   : str       # 调用方提供的稳定 id；缺失时系统生成 uuid4
dedupe_key : str       # 幂等去重键；event_id 存在时直接使用，否则由 source+uid+payload 哈希生成
char_id    : str       # 活跃角色 id；None → 从 active_prompt_assets.json 解析，fail-loud
source     : str       # 来源标识（desktop_wake / qq / scheduler / sensor / ...）
trust      : str       # low_trust（外部/定时/sensor）| high_trust（管理接口直发，目前未使用）
timestamp  : float     # Unix epoch，事件生成时间
```

v0.1 这些字段的实际位置：
- `event_id / dedupe_key / source / char_id`：`PerceiveEvent` dataclass（`core/perceive_event.py`）
- `trust`：`PerceiveEvent` 的显式字段。省略时由 `source` 推导；当前 scheduler、sensor、desktop wake 等既有来源均为 `low_trust`，调用方可显式覆写为 `high_trust`
- `timestamp`：`PerceiveEvent` 内部与 trigger audit log 均使用 Unix epoch

---

## 三、当前实现边界（v0.1）

### 3.1 perceive_event 是 reality-side low-trust stimulus gate，不是完整 event bus

`core/perceive_event.py` 只做三件事：
1. **幂等去重**：90 秒 TTL 进程内字典，相同 dedupe_key 在窗口内只通过一次
2. **Dream Guard**：`DREAM_ACTIVE / DREAM_CLOSING` 时拒绝 reality 事件（`BLOCKED_DREAM`）
3. **返回 PerceiveStatus**：调用方凭此决定是否继续进入 pipeline

它**不是**事件路由器，不做 kind dispatch，不维护 session 状态，不写任何存储。

Stage 同样不把 `perceive_event` 当作 session 路由器。`core/stage/runner.py` 只接受已经确定属于某个
Stage 的 owner turn，并在 Stage 自己的锁与 transcript 边界内编排回复。

### 3.2 "trigger" vs "stimulus" 命名

| 层面 | 名称 |
|---|---|
| 概念文档（本文） | `stimulus` |
| 代码 / 文件名 / 函数名 | `trigger`（v0.1 保持不变） |
| 日志 / audit `kind` | `stimulus` |

代码层 `trigger` 对应概念层 `stimulus`：系统主动发起的、非用户直接输入的单次事件。重命名代码面未排期；不得因此改变调用路径或 gate 语义。

### 3.3 关键约束（v0.1 不变量）

| 约束 | 说明 |
|---|---|
| **tool result never re-enters as stimulus** | 工具执行结果通过 `tool_result` prompt 层注入当前轮，不重新经过 perceive_event gate，不产生新的 kind=stimulus 事件 |
| **stimulus cannot implicitly upgrade to tool** | stimulus/trigger 事件触发 LLM 生成，但生成结果中的 desktop intent 走 intent parser，不作为 kind=tool 事件回注；tool 调用是显式的，不由 stimulus 隐式升级 |
| **dream does not go through reality gate** | `POST /dream/chat` 直接进入 dream pipeline，完全绕过 `receive_perceive_event()`；Dream Guard 反向保护现实侧，不是梦境侧的入口守卫 |
| **LLM reply outlet: kind ∈ {message, stimulus}** | 助手回复通过 `record_assistant_turn / turn_sink` 广播，归属于触发本轮的 kind；系统不从 LLM 回复中派生新的 kind=tool 或 kind=activity 事件 |
| **Stage session is explicitly driven** | Stage 由上游显式创建、关闭和调用；P2 不通过 `perceive_event` 自动发现或推进 Stage，也不把 AI 续聊重新注入 event gate |

### 3.4 Trigger Audit Log（v0.1 可观测性）

每个经过 perceive_event 的 stimulus 写一条 audit 记录，含：
- `event_id`、`dedupe_key`、`gate_result`（`ACCEPTED / DUPLICATE / BLOCKED_DREAM / IGNORED / ERROR`）
- `source`、`uid`、`char_id`
- `trust`（`low_trust` / `high_trust`）与 `kind="stimulus"`
- `timestamp`

只读观测入口：`GET /observability/perceive-events`（`state.read` scope），支持 `source`、`gate_result` 精确过滤及 `offset` / `limit` 分页。

**Trigger 不写 short_term**：stimulus 事件触发的助手回复通过正常 `record_assistant_turn` 写 short_term（`bypass_gate=True`），但 stimulus 事件本身不写任何 short_term 记录。

### 3.5 MCP 边界

- **MCP invocation is not an event kind.** 不创建 `kind=mcp`，MCP 工具调用生命周期继续属于
  tool subsystem。
- MCP results never re-enter as stimulus：结果只作为当前轮 bounded ToolResult/tool message
  回注，不重新经过 `perceive_event`，不写入该 gate 的 audit，也不成为新的现实刺激。
- MCP does not turn `perceive_event` into a dispatcher。`perceive_event` 仍只是 reality-side
  low-trust stimulus gate，不负责按 MCP 或其他 kind 路由。
- 这不构成 v1 `EventEnvelope`、统一 dispatcher 或 EventBus 承诺；MCP 的 session、动态工具
  注册/摘除和调用取消仍由现有 tool subsystem 管理。

---

## 四、事件流图（v0.1 简化）

```
用户输入 (message)
  └─ perceive_event [reality gate: dedup + dream guard]
        └─ ACCEPTED → conversation_lock → Pipeline → LLM → record_assistant_turn
              └─ turn_sink → channels.broadcast (reality)

系统触发 (stimulus / trigger)
  └─ scheduler._pipeline_send / sensor / desktop_wake
        └─ perceive_event [reality gate]
              └─ ACCEPTED → conversation_lock → Pipeline → LLM → record_assistant_turn
                    └─ turn_sink → channels.broadcast (reality)

工具结果 (tool result)
  └─ 注入 prompt 层 10 (tool_result)，参与当前轮 LLM 生成
        NOT re-injected as stimulus

梦境输入 (dream message)
  └─ POST /dream/chat → dream pipeline（完全绕过 reality gate）
        └─ dream log（不写现实记忆）
```

---

## 五、Historical / deferred design (not a v1 commitment)

以下内容尚未实现，也不因产品发布称为 v1 而自动进入范围。在另行批准并完成跨仓兼容设计前，禁止据此创建统一 dispatcher 或替换现有入口：

- `EventEnvelope` dataclass（统一封包，目前各入口各自 PerceiveEvent / TriggerProposal）
- dispatch router（按 kind 路由到不同处理器）
- `kind=tool` 独立 event 类型（工具调用生命周期管理）
- `kind=activity` + `ActivitySession`（活动会话状态机）
- Stage 的 Pipeline / prompt / memory projection 适配（P2 仅实现独立 Session 内核）
- `channel_message` 结构变更
- plugin 系统
- trust-based gating（例如高信任来源跳过 dedup 等；本次仅字段化，不改变 gate）
- 跨 realm event（梦境→现实的结构化事件，目前只有 afterglow 回流）

---

## 六、与其他文档的关系

| 文档 | 关系 |
|---|---|
| `docs/channels.md` | 通道层（broadcast / fanout），位于 event 处理的下游 |
| `docs/stage.md` | 多角色 Stage session、共享 transcript、仲裁与当前接入边界 |
| `docs/dream.md` | Dream realm 的完整规格（pipeline / prompt / 隔离合同） |
| `docs/trigger-decision-layer.md` | Stimulus 决策层设计（gating / propose / state machine） |
| `docs/scheduler.md` | 调度器触发器（stimulus 的主要生产者之一） |
| `docs/tools.md` | Tool 系统（独立 `kind=tool` 仍是 deferred design） |
