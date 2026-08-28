# 225 · Autonomy 持锁评估导致 owner 聊天卡死 / 可能死锁

> 状态：`open`（2026-08-27 诊断完成，**本工单未实施**）  
> 前置：Brief 224 已上线（admission 不再被僵尸 `dream_seed` 永久挡住）  
> 禁止：回滚 224 的 admission/预算/TTL 修复来“治”本问题；禁止恢复 `_pipeline_send`

## 一、现场现象

部署 224 后：当场能回复；过一段时间后 **正常消息一直加载**，主动消息也没有。  
进程仍活着，journal **没有** owner-chat traceback。Luna 报错出现在 **已经成功返回的那一轮之后**，不能解释加载中。

关键时间线（服务器 journal，2026-08-27）：

| 时间 | 事件 | 含义 |
|---|---|---|
| 15:01:26 | `[owner_chat/timing] channel=mobile ... total=4.24s` | **主聊天已成功** |
| 15:01:27 | `detect_emotion` / `detect_affection` / `summarize_turn` 对 `gpt-5.6-luna` 报 `UpstreamResponseFormatError` | **send 后慢路径**，已降级，不是主链路 |
| 15:01:29 | DeepSeek `purpose=chat` 1.6s + 画像更新完成 | 慢队列仍在干活 |
| 15:16:37 | DeepSeek `purpose=chat` **34695ms** | 很像在等锁或等长评估 |
| 15:16 之后到 23:58 | **再也没有** `[owner_chat/timing]` | 后续请求卡在 lock 之前，timing 打不出来 |
| 23:58 | model_registry rebuild | 像是改配置/热重载，不是聊天恢复 |

Luna 一直能当辅助模型用。主对话走的是 `deepseek-v4-flash`。不要把本工单做成「修 Luna Responses 格式」——那是独立小债，不解释加载中。

## 二、根因（代码已核对，不是猜测）

`asyncio.Lock` **不可重入**。owner 聊天和 autonomy 评估共用 `core/conversation_gate.py::conversation_lock(uid)`。

### 路径 A：评估期间堵住聊天（必现级）

224 之前：admission 几乎全是 `blocked_user_active`，`run_job` 在拿锁前 return（现场 11ms）。  
224 之后：admission 能过 →

```text
scheduler loop
  await autonomy.runner.tick()
    await run_job()
      async with conversation_lock(uid):   # core/autonomy/runner.py ~462
        await _run_locked()                # llm_client.chat_turn，deadline ≈ total_timeout_seconds 默认 120s
```

owner 入口 `admin/routers/chat.py::run_owner_chat_turn` 同样：

```text
async with conversation_lock(user_id):
    fetch_context → LLM → critical post_process
```

评估一旦开始，用户消息在锁外排队，前端一直转圈。journal 没有新的 timing 行。

### 路径 B：talk_owner 二次拿锁（永久死锁）

`talk_gate.send()` 默认：

```text
record_assistant_turn(..., bypass_gate=False)
  → turn_sink._maybe_conversation_gate
    → 再 async with conversation_lock(uid)
```

调用栈已在 `run_job` 的 `async with lock` 内。同一 task 二次 acquire **永远等自己**。  
`keeper` 只续 lease，**不会**取消 `_run_locked`，也 **不会**放 conversation_lock。  
此后该 uid 的所有 owner chat / 下一次 autonomy 评估全部挂死，直到进程重启。

这是 **原有耦合**。224 只是第一次让评估走进锁，把坑暴露出来。

### 不是什么

- 不是 git 数据回滚问题（`data/` 全 ignore）
- 不是 Luna 主聊天协议突然坏了
- 不是 message_queue worker 崩了（15:01 那轮已经走完 owner_chat）
- 不要用「提高开口率」或直发旁路来修

## 三、目标

1. autonomy 评估 **不得**在整段 LLM 期间占有 owner `conversation_lock`。
2. `talk_owner` 不得在已持锁时再 `bypass_gate=False` 拿同一把锁。
3. 评估必须有硬超时，超时必须放锁、finish run（`timeout`），不能把 scheduler tick 和聊天一起卡死。
4. 224 的 admission/预算/TTL 语义保持不变。
5. 回归测试必须覆盖：评估进行中 owner chat 仍能进入；`talk_owner` 在持锁上下文中能 send 且不死锁。

## 四、推荐改法（按优先级）

### 1. 立刻止血（P0）

`core/autonomy/talk_gate.py::send` → `record_assistant_turn(..., bypass_gate=True)`。

理由：外层 `run_job` 已经持锁（若仍持锁）；`turn_sink` 文档写明 `bypass_gate=True` 给「已在 conversation_lock 内」的调用方。QQ adapter 已有先例。  
若第 2 步改为「评估不持锁」，send 时再短持锁也可以，但 **当前代码在修完第 2 步之前必须 bypass**，否则死锁仍在。

### 2. 评估与聊天解耦（P0，产品正确）

`run_job` **不要** `async with conversation_lock` 包住 `_run_locked`。

建议语义：

- 入评估前：现有 `lock.locked()` 检查保留（用户正在聊则 `blocked_user_active`，不要插队）
- `_run_locked`（LLM/工具）**无** conversation_lock
- 仅 `talk_gate.send` / `record_assistant_turn` 短持锁（或 send 自己拿锁且 `bypass_gate=False`，但不要两层）
- 评估中途用户开口：已有 `_user_became_active` → `canceled_by_user_activity`；确保取消后立刻 finish，不继续占模型预算

不要把 autonomy 评估塞进 owner-chat pipeline。

### 3. 硬超时与 scheduler 隔离（P0）

- `_run_locked` 已有 `total_timeout_seconds` + `asyncio.wait_for`；确认 TimeoutError 路径一定 `_finish` + `store.finish`，**finally 放锁**（若还持锁）
- `scheduler/loop.py` 里 `await _autonomy_tick(...)` 应再包一层 wait_for（略大于 job timeout），tick 失败不得卡住整轮维护
- lease keeper 在 timeout/cancel 时必须停

### 4. 观测（P1，跟代码一起）

加载中时 journal 现在是空的。至少打：

- `[autonomy.run_job] acquire conversation_lock uid=...` / `release`
- `[owner_chat] waiting conversation_lock uid=... waited_ms=`
- run disposition `timeout` / `lease_lost` 计数

否则下次只能再猜。

## 五、不要做

- 不要回滚 224（僵尸 session / 预算记账会回来，聊天未必好，主动消息必哑）
- 不要为解死锁去还原整份 `data/`
- 不要改 Luna 当本工单主修复（另开小单：slow-path Responses 缺 `completed`）
- 不要让 `talk_owner` 再进 `run_owner_chat_turn`（会再次叠锁和套 pipeline）

## 六、关键文件

| 文件 | 角色 |
|---|---|
| `core/autonomy/runner.py` | `run_job` 持锁评估 |
| `core/autonomy/talk_gate.py` | `send` → `bypass_gate=False` |
| `core/turn_sink.py` | `_maybe_conversation_gate` |
| `core/conversation_gate.py` | 不可重入 `asyncio.Lock` |
| `admin/routers/chat.py` | owner chat 同锁 |
| `core/scheduler/loop.py` | `await _autonomy_tick` 无外层超时 |
| `tests/test_autonomy.py` 等 | 补死锁/并发回归 |

## 七、验收

1. 单测：mock 住 lock，在「已持锁」上下文调用 `talk_gate.send`，必须在短时间内返回，不能挂住 event loop。
2. 单测：`run_job` 评估中（mock 慢 LLM），并发 `run_owner_chat_turn` 能获取锁或明确不等待评估结束（按第 2 步语义）。
3. 手工：部署后 QUIET 期让 autonomy 跑起来，同时从 mobile 发消息，应秒级进入 `[owner_chat/timing]`，而不是一直转圈。
4. 若仍转圈：`locked_conversation_uids()` 和最新 autonomy run 的 `started_at`/`finished_at`/`disposition` 必须能对上。

## 八、运维（现网已卡死时）

回滚代码 **不解** 当前进程里的 asyncio.Lock。必须 **重启 presencekit**。  
`data/` 不必回滚。224 关掉的 dream_seed 保持 closed。
