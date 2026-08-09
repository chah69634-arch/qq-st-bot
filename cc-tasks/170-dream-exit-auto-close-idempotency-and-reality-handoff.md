# Brief 170：Dream 退出自动回到 Chat、真正幂等与 Reality 连续交接

## 背景与真实现场

单人 Dream 有两条客户端退出感知路径：

1. `/dream/chat` 当前响应直接返回 `exit_accepted/force_exited` 时，`useDreamChat()` 调用 `onExited()`，
   DreamWindow 关闭。
2. 后端通过轮询被观察为 `DREAM_CLOSING` / `REALITY_AFTERGLOW` 时，DreamWindow 只把 phase 设为
   `ended`、禁用输入并显示“按 WAKE 醒来”，不会自动回到 Reality Chat。

第二条路径下用户再次按 WAKE，`POST /dream/wake` 在非 active 状态又调用 `force_exit_dream()`。
`_do_close_dream()` 只保护空 dream_id 不覆盖 `last_dream_id`，但仍会用已清空 state 的默认 sandbox
mode 和 `system_fallback` 覆盖上一场真实的 `last_dream_mode`、exit mechanism/initiator/reason、assistant
turns 与时间。现场已出现 summary 为 scenario、dream_state 却被覆盖成 sandbox/system_fallback；随后
`dream_exit` 错按 Sandbox 等待不存在的 afterglow。

现有 Reality `dream_exit` proposer 还与普通 scheduler 候选竞争。多场 lifecycle 长期停在
`higher_priority_winner` 或因被覆盖的 mode 停在 `afterglow_not_ready`，无法实现用户明确退出后的连续
Reality 回应。

## 产品决定

- 后端一旦真实关闭，DreamWindow 自动消失并回到 Chat；不再要求用户对已关闭梦再按 WAKE。
- “幂等”包括元数据不变：对已关闭梦重复 wake/exit 不得二次归档、二次 summary、二次 lifecycle seed
  或覆盖任何 last-exit 字段。
- 用户明确请求退出且角色通过机器合同接受，是同一次用户交互的 Reality continuation，不是普通主动
  scheduler 候选；它不应与日记/topic followup 等争 winner。
- 真正未来的角色单方面主动离梦仍属于主动行为，另行遵守 DND/主动策略；本 Brief 不借
  `character_accept` 名称扩大到无用户退出请求的单方面关闭。

## 范围 A：服务端退出 chokepoint 真正幂等

- `force_exit_dream()` / `_do_close_dream()` 在入口确认存在 active/exit-requested/closing dream_id；已处于
  Reality 且没有 active dream 时返回结构化 `already_closed` no-op，不再调用 close pipeline。
- `/dream/wake` 在非 active 状态直接返回 `retained=false, exited=true, already_closed=true`，不得用
  `system_fallback` 重写上一场。
- `/dream/exit` 重复调用同样 no-op 成功，硬退出在活跃梦中的绝对穿透不变量不变。
- 第一次真实关闭原子保存 dream_id、mode、world、exit mechanism/initiator/completion/reason、turn counts、
  archive result、exited_at；后续调用只读返回同一关闭结果。
- 只为非空真实 dream_id 创建 summary、afterglow、postcard eligibility 与 exit lifecycle；每项按 dream_id
  幂等。
- 修正文档/字段命名读取：state 的 canonical completion 字段保持单一名称；API/operations 不能一处读
  `last_completion`、另一处读不存在的别名而显示空白。

## 范围 B：客户端自动退出 DreamWindow

- DreamWindow 记录本次已观察到的 active dream_id/status；只有从
  `DREAM_ACTIVE|DREAM_EXIT_REQUESTED` 跨到 `DREAM_CLOSING|REALITY_AFTERGLOW|REALITY_CHAT` 的真实跃迁才
  自动 `onClose()`。
- 初次打开 DreamWindow 且后端本来就在 Reality 时仍显示 entry/replay 页面，不因普通 reality 状态
  自动关闭。
- HTTP `exit_accepted` callback 与 poll transition 可以同时到达，close 必须幂等且只触发一次 afterglow
  UI/导航副作用。
- 自动关闭前保留/送达本轮角色可见结尾；不能因卸载过早丢掉 HTTP reply、archive 或 pseudo-stream final。
- 返回 Chat 后恢复 parked Reality WS 消息的既有一次性 flush，不重复、不丢失；不得伪造一次
  `desktop_wake` 来代替后端 Reality handoff。
- ended 页面只保留为 archive/reconnect 异常诊断 fallback，不再是正常退出流程的必经页面。

## 范围 C：用户退出后的 durable Reality continuation

### 资格边界

只对以下完整事实同时成立的关闭建立 continuation：

- 本轮用户消息被现有明确退出请求规则识别；
- `dream_control.exit == accept`；
- `_do_close_dream()` 首次真实关闭成功并进入 Reality；
- 同一 dream_id 尚未发送 continuation。

硬退 `/stop`、WAKE 强制离开、network fallback、已关闭重复调用默认仍走现有安全策略，不自动伪装成
角色接受后的连续回应。

### 调度与执行

- 在 Dream 可见回复已经产生并返回后，异步种入 durable continuation；不得在 send 前 await 第二次
  LLM/网络往返。
- continuation 走正常 Reality `fetch_context → build_prompt → LLM → turn_sink → fanout`，由原做梦
  char_id 发言；绝不复用 Dream Prompt 或把梦境正文塞入 Reality。
- 它是对用户明确退出请求的后半段响应，不要求 scheduler QUIET、全局 proactive gap、普通 winner 或
  proactive budget；但必须等待 Dream close 完成、遵守 conversation gate、一次一梦、失败可重试且不能
  与新的用户 Reality turn 并发覆盖。
- 若用户已经在 Reality 发出新消息，新的 live user turn 优先；continuation 进入有界 defer 或取消并写
  固定 reason，不能插到用户新回复中间。
- Prompt 只使用安全事实：“刚从一场梦回到现实”，可消费已经存在的 Reality afterglow soft hint；不得
  引用梦境 archive、剧情、私密真相或控制块。
- 发送成功后才写 sent/idempotency marker。服务重启、客户端关闭或 WS 重连不能重复发送。

### 生命周期观测

- 复用并扩展现有 `exit_lifecycle.json`，不要另造平行总账；增加安全 delivery kind/status/reason 以区分
  `continuation` 与普通 `scheduled_greeting`。
- “后端管理面板 → 观测 → 梦境运维”显示 close metadata 是否一致、客户端应否已自动退出、continuation
  `pending|deferred|sent|cancelled|failed` 与固定 reason。
- 不记录用户退出原文、角色 Dream 回复、Reality 回复、Prompt、邮箱、路径或其他正文。

## 范围 D：现有普通 dream_exit 调度修正

- continuation 成功后设置与 `last_greeted_dream_id` 兼容的去重事实，使普通 proposer 不再为同一梦补发。
- 非 continuation 梦仍可走现有 `dream_exit` scheduler；其 aging、DND、QUIET、预算和 winner 合同不因本
  Brief 全局放宽。
- 修复 mode/metadata 后，Scenario 不再误走 Sandbox afterglow 等待；普通 proposer 的
  `waiting_afterglow/ready/blocked/sent/expired` 仍可观测。

## 不在范围内

- 不允许角色在没有机器控制合同、没有用户退出请求时仅凭自然语言台词单方面关闭梦。
- 不扫描“醒来/离开”等可见角色回复关键词猜退出。
- 不取消 active Dream 的 `/stop` 绝对出口，不给 hard exit 增加 LLM、确认或锁等待。
- 不让 Dream archive/summary/private truth 进入 Reality memory 或 Prompt。
- 不修改 Scenario Prompt/阶段推进（Brief 169）或回放渲染（Brief 168）。

## 预计主要文件

后端：

- `core/dream/dream_pipeline.py`
- `core/dream/dream_state.py`
- `core/dream/exit_contract.py`
- `core/dream/exit_observability.py`
- durable continuation worker/queue（如需新模块，状态仍收口进现有 lifecycle）
- `core/scheduler/triggers/dream_exit.py`
- `core/conversation_gate.py` / `core/turn_sink.py`（只复用，不改全局语义）
- `admin/routers/dream.py`
- `admin/static/pages/observe-dream-operations.html`
- `admin/static/js/dream-operations.js`、i18n/cache
- `docs/dream.md`、`docs/scheduler.md`、`docs/runtime-lifecycle.md`

桌面：

- `src/windows/dream/DreamWindow.tsx`
- `src/windows/dream/hooks/useDreamChat.ts`
- `src/windows/chat/hooks/useChatWindowNavigation.ts`
- `src/windows/chat/ChatWindow.tsx` / parked-message tests（仅必要接线）
- Dream/navigation focused tests 与文档

## 验收标准

1. active Dream 首次 soft accept/hard exit 仍可靠归档并进入 Reality；`/stop` 始终立即成功。
2. 关闭后重复 WAKE、exit 或 callback 不改变 last_dream_id/mode/mechanism/initiator/completion/reason/time，
   不产生第二份 summary/lifecycle/postcard 工作。
3. poll 观察到 active→closed 时 DreamWindow 自动回到 Chat；HTTP callback/poll 竞态只关闭一次。
4. 初次在 Reality 打开 DreamWindow 仍可进入、设置和回放，不被自动关闭。
5. 用户明确退出且角色接受后，Reality continuation 在 Dream 回复之后异步生成并通过正常 turn sink 一次
   送达，不与普通 scheduler winner 竞争。
6. 用户先发出新的 Reality 消息时不发生并发插话；defer/cancel reason 可观测。
7. 重启、断线、客户端关闭和重连不丢 durable pending，也不重复 sent。
8. Scenario mode 不再因重复 WAKE 被覆盖成 Sandbox；梦境运维能解释 close 与 delivery 状态。
9. parked Reality 消息只 flush 一次，普通 desktop wake、DND 与非 continuation proactive 行为零回归。

## 验证

- 后端 focused `pytest -n auto`：所有 status × exit endpoint 幂等矩阵、metadata preservation、双 callback、
  summary/lifecycle single seed、continuation eligibility、restart/retry、new user turn race、turn sink success/fail。
- 桌面 Vitest：HTTP accept、poll close、二者竞态、initial Reality open、reply finalization、parked flush、reconnect。
- 真实测试隔离 E2E：enter → 多轮 → 用户请求退出 → 角色 accept → 自动回 Chat → Reality continuation 一次
  出现 → operations 显示 sent；再点/调用 exit 不改状态。
- 另测 `/stop`、WAKE hard exit、LLM control missing、客户端在关闭点断线和服务重启。
- `npx.cmd tsc --noEmit`、`npm.cmd run build`；Rust 未改无需 cargo；后端 py_compile/node check。
- 管理面和 DreamWindow 真实目检；未完成 E2E/目检则整单只能 partial。
- 两仓 `git diff --check`，不得夹带当前 Emerald-client 的并行 UI 改动。

## 建议提交边界

1. 后端 close idempotency 与 metadata preservation，独立 commit。
2. 客户端 active→closed 自动返回 Chat，独立 commit。
3. durable Reality continuation、普通 proposer 去重与 operations 观测，独立 commit。
4. 跨仓 E2E 仅补必要修正和验收证据，不压成一个大提交。
