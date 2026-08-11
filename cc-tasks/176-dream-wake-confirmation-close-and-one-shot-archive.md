# Brief 176：Dream WAKE 二次确认收口、一次性封存与只读回放边界

## 背景与现场结论

Dream 的既定产品语义不是“按 WAKE 必然立刻退出”，也不是“退出后还能续梦”，而是：

- 角色在梦内接受/发起结束时，本场梦直接结束；
- 用户主动按 WAKE 时，角色在满足既有门控时可以挽留一次；
- 用户选择“留下”时，仍留在**同一场尚未结束的梦**；
- 用户选择“还是要醒来”或再次按 WAKE 时，本场梦立即、不可逆地结束；
- 已结束的梦只允许从 archive 只读回放，不能恢复为 current session，也不能继续写入。

当前生产现场出现：用户第一次按 WAKE 后进入 `DREAM_EXIT_REQUESTED`，随后确认醒来却没有关闭；重新打开
DreamWindow 仍显示同一个 `dream_id` 和 current transcript。

根因在 Brief 170 的幂等关闭接线：`POST /dream/wake` 对任何非 `DREAM_ACTIVE` 状态直接返回
`already_closed=true`，但 `DREAM_EXIT_REQUESTED` 实际仍是一个有效、尚未封存的 session。于是第二次 WAKE
没有调用 `force_exit_dream()`，`current_dream_{uid}.jsonl` 没有迁入 archive，`dream_id` 也没有清空。客户端又
按既有软挽留合同把 `DREAM_EXIT_REQUESTED` 投影成 active，重开后自然恢复了同一场梦。

这是状态分类耦合错误，不应通过删除软挽留、删除“留下”能力或把 `DREAM_EXIT_REQUESTED` 粗暴当成 closed
来修复。

## 已决定的产品状态机

| 当前状态 | 用户动作/系统事件 | 必须结果 |
|---|---|---|
| `DREAM_ACTIVE` | 角色接受/发起梦内结束 | 立即 close + archive，进入 `REALITY_AFTERGLOW` |
| `DREAM_ACTIVE` | 用户首次 WAKE，挽留门控不通过或生成失败 | 立即 close + archive，进入 `REALITY_AFTERGLOW` |
| `DREAM_ACTIVE` | 用户首次 WAKE，挽留成功 | 进入 `DREAM_EXIT_REQUESTED`；本场尚未结束，等待用户选择 |
| `DREAM_EXIT_REQUESTED` | 用户选择“留下” | 回到 `DREAM_ACTIVE`；保留同一 `dream_id` 和 current transcript |
| `DREAM_EXIT_REQUESTED` | 用户选择“还是要醒来”或再次 WAKE/Esc | 立即 close + archive，进入 `REALITY_AFTERGLOW` |
| `DREAM_CLOSING` / `REALITY_AFTERGLOW` / `REALITY_CHAT` | 重复 WAKE/EXIT | 幂等返回既有首次关闭结果，不重复 archive/summary/lifecycle |
| archive replay | 任何输入、发送、resume、WS/伪流式动作 | 拒绝或不暴露；只读展示 |

关键定义：`DREAM_EXIT_REQUESTED` 是“退出确认待决”，不是“已经关闭”。只有 `_do_close_dream()` 成功执行并
把 active state 转成 `REALITY_AFTERGLOW`，才算这场梦结束。

## 范围 A：修正后端 WAKE 状态分类

- 修改 `admin/routers/dream.py::dream_wake()`：
  - `DREAM_ACTIVE` 保持现有首次 WAKE/软挽留门控；
  - `DREAM_EXIT_REQUESTED` 必须调用 `force_exit_dream()`，并携带明确的用户确认退出 metadata；
  - `DREAM_CLOSING`、`REALITY_AFTERGLOW`、`REALITY_CHAT` 等真正非 active 状态才返回幂等
    `already_closed` 结果；
  - 未知/损坏状态 fail-closed，不得伪报 archive 成功，也不得创建新梦。
- 为“首次 WAKE 未触发挽留而直接醒来”和“挽留后用户确认醒来”使用可区分但稳定的
  `exit_mechanism` / `exit_reason`，不得继续把用户明确确认醒来记为 `system_fallback`。
- 保持 `/dream/exit` hard exit 绝对可用；本 Brief 不削弱 `/stop`、hard exit 或异常恢复出口。
- `force_exit_dream()` / `_do_close_dream()` 继续作为唯一关闭收口，不在 router 复制 archive、summary、
  afterglow、continuation 或 lifecycle 写入。

建议新增/规范化的原因码应复用 `core/dream/exit_contract.py` 的集中定义；若确需新增，至少覆盖：

- `user_wake_no_retention`：用户首次 WAKE，无挽留而直接醒来；
- `user_wake_confirmed_after_retention`：角色挽留后，用户仍确认醒来；
- `user_hard_exit`：显式 hard exit，保持既有含义；
- `character_accepted`：角色接受/发起梦内结束，保持既有含义。

具体字符串可在施工时按现有 contract 命名统一，但不得把上述语义重新合并成无法观测的单一
`system_fallback`。

## 范围 B：保持“留下”能力但收紧 session 身份

- 保留 `/dream/resume` 与客户端“留下”按钮；它们是软挽留设计的一部分，不是本次回归本身。
- `/dream/resume` 只能在 `status == DREAM_EXIT_REQUESTED` 且请求关联的 `dream_id` 与当前 state 完全一致时
  生效；过期窗口、旧响应或 archive dream 不得复活当前 state。
- 建议客户端在 `dreamWake()` 返回 retention 时保存该 `dream_id`，`dreamResume()` 与确认离开都携带该
  session identity；后端 mismatch 返回固定 409/no-op，不作用于后来新开的梦。
- resume 成功只做 `DREAM_EXIT_REQUESTED -> DREAM_ACTIVE`，不新建 dream、不清 transcript、不重建 frozen
  snapshot。
- resume 失败时客户端不得静默清掉挽留 UI 并假装已恢复；必须刷新 `/dream/state`，按后端真值决定关闭、
  继续显示选择，或给出可重试错误。

## 范围 C：客户端 WAKE/关闭接线

- `DreamWindow.handleWake()` 保持首次调用软挽留接口。
- 挽留 UI 中：
  - “留下”调用带当前 `dream_id` 的 resume；成功后才清除挽留态并恢复输入；
  - “还是要醒来”调用确认关闭路径，等待后端返回 `closed_now` 或可信 `already_closed` 后关闭窗口；
  - 再次点击 WAKE 或在挽留选择态按 Esc，与“还是要醒来”同义，不能只关闭 Webview overlay。
- `handleForceExit()` 不得吞掉后端/网络失败后无条件关闭窗口并制造“已经醒来”的假象。hard exit 的产品
  保证应由后端成功结果证明；网络失败时保留可重试出口并刷新 state。
- 保持 Brief 170 的自动关闭：观察到同一个 `dream_id` 从 active/exit-requested 转为
  `DREAM_CLOSING | REALITY_AFTERGLOW | REALITY_CHAT` 时自动关闭 DreamWindow。
- `DREAM_EXIT_REQUESTED` 在等待选择期间仍可展示当前 transcript，但输入必须禁用；只有 resume 成功才恢复
  写入能力。
- 群聊 Dream 不引入软挽留；现有 group WAKE 仍直接 hard close，本 Brief 不扩展 Group Dream 状态机。

## 范围 D：一次性封存与只读回放不变量

每条真正结束路径——角色接受退出、首次 WAKE 直接退出、挽留后确认退出、hard exit——都必须收敛到同一组
持久不变量：

1. state 不再是 `DREAM_ACTIVE` / `DREAM_EXIT_REQUESTED` / `DREAM_CLOSING`；
2. active `dream_id` 被清除，`last_dream_id` 固定为首次关闭的 ID；
3. `tmp/current_dream_{uid}.jsonl` 不存在；
4. 对应 `archive/dream_{dream_id}.jsonl` 存在，内容等于关闭前 current transcript；
5. archive replay API 能读到它，但 Dream chat/send/resume 不能把它重新挂为 current；
6. 重复 WAKE/EXIT 不覆盖首次退出 metadata，不重复 summary、afterglow、postcard eligibility、Reality
   continuation 或 lifecycle seed；
7. 新一场梦必须分配新的 `dream_id` 和新的 current transcript，不能 append 到旧 archive。

若 `archive_current()` 返回失败，关闭结果和观测必须明确 `archive_ok=false`；不得把窗口关闭当作“一次性封存已
验收”。本 Brief 不删除或自动迁移真实残留 current 数据。

## 范围 E：生产残留状态的安全恢复

当前和升级时可能已存在合法形状的 `DREAM_EXIT_REQUESTED` 残留。施工必须提供显式恢复策略：

- 不在启动时静默 resume；
- 不直接删除 current transcript；
- UI 重开后仍显示挽留选择，用户“留下”则继续，用户“醒来”则走正常 close + archive；
- 可在后端 Dream 运维观测中标记 `exit_confirmation_pending`、age、dream_id 脱敏摘要和 archive/current
  presence，供人工判断；不得显示 transcript 正文；
- 若增加人工恢复操作，必须复用 `force_exit_dream()` 且保持 scope/确认合同，不另写文件搬运捷径。

本 Brief 不自动操作现有生产 `data/runtime`，不把现场残留梦当测试夹具改写。

## 范围 F：观测、文档与协议同步

- 更新 `docs/dream.md`，明确区分：
  - soft retention pending（梦尚未结束）；
  - resumed（用户明确留下）；
  - confirmed wake（梦已不可逆结束）；
  - hard exit；
  - archive replay（只读）。
- 更新 `docs/runtime-lifecycle.md` 与必要的桌面 Dream 文档，记录跨进程状态与失败语义。
- 后端 Dream operations/exit observability 必须能回答：首次 WAKE 是否挽留、用户最终选择、关闭是否真的
  执行、archive 是否成功、是否发生重复幂等调用。
- 不记录用户/角色正文、Prompt、完整 transcript、token 或本机绝对路径。
- 若改动客户端可见文案，走语义 i18n key；不要继续在 `DreamWindow.tsx` 写死新中文。

## 预计主要文件

Presence backend：

- `admin/routers/dream.py`
- `core/dream/dream_pipeline.py`
- `core/dream/exit_contract.py`
- `core/dream/dream_state.py`
- `core/dream/dream_log.py`（只补守卫/测试需要时，避免重写 archive primitive）
- `core/dream/exit_observability.py`
- `tests/test_dream_*.py` 中 focused exit/wake/archive suites
- `docs/dream.md`
- `docs/runtime-lifecycle.md`

PresenceKit desktop：

- `src/windows/dream/DreamWindow.tsx`
- `src/shared/api/dream.ts`
- `src/shared/api/dream-types.ts`
- `src-tauri/src/lib.rs` 中 Dream command bridge（若请求/响应需携带 dream_id）
- Dream 纯逻辑 helper/tests；必要时把状态转移判断从组件拆成无副作用函数
- `docs/dream-hud.md` / `docs/backend-integration.md` / `docs/design-constraints.md`

## 验收标准

1. `DREAM_ACTIVE` 首次 WAKE、门控通过：只进入 `DREAM_EXIT_REQUESTED`，不 archive，不清 `dream_id`，输入禁用。
2. 挽留后点“留下”：相同 `dream_id` 回到 `DREAM_ACTIVE`，current transcript 原样保留且可继续对话。
3. 挽留后点“还是要醒来”：调用唯一 close 收口，状态进入 afterglow，current 文件消失、archive 文件出现，
   DreamWindow 自动关闭。
4. 挽留态再次按 WAKE 或 Esc 与“还是要醒来”完全等价，不返回假 `already_closed`，不只关 UI。
5. 首次 WAKE 门控不通过/挽留生成失败：直接完成同样的一次性 archive，不停在 exit-requested。
6. 角色接受/发起梦内结束继续直接 close；不被 soft retention 路由拦截，也不出现“留下”按钮。
7. `/dream/exit` 与 `/stop` 在任意 active/exit-requested 状态仍能 hard close；网络/服务端失败不伪报成功。
8. 对已关闭梦重复 WAKE/EXIT 返回首次关闭 metadata，archive/summary/lifecycle/continuation 各只产生一次。
9. archive replay 可读且只读：无输入、无 send、无 resume、无 current write、无 TTS/WS/伪流式副作用。
10. 关闭旧梦后新入梦获得新 `dream_id` 和空白 current；选择旧 archive 回放不会改变新梦 state。
11. 过期 retention 响应对后来新梦执行 resume/confirm 时被 dream_id guard 拒绝，不会关闭或复活错误 session。
12. 当前生产式 `DREAM_EXIT_REQUESTED + current transcript` 残留可由用户选择安全收口，不删数据、不静默续梦。

## 验证

- 后端状态矩阵 focused tests：
  - active → retained → resume；
  - active → retained → confirm wake；
  - active → no retention → close；
  - active → retention LLM fail → close；
  - exit-requested → second WAKE/Esc-equivalent → close；
  - active/exit-requested → hard exit；
  - closing/afterglow/reality → duplicate idempotent result；
  - stale dream_id resume/confirm → rejected/no mutation。
- 文件不变量测试：关闭前 current 内容、关闭后 archive byte/content、current 删除、重复调用不覆盖 archive、新梦
  不复用旧 ID。
- lifecycle/observability 测试：reason、initiator、completion、archive_ok、首次关闭 metadata 与重复调用计数；
  不含正文。
- 客户端 Vitest：WAKE 结果分类、retention stay/leave、Esc、失败重试、state polling auto-close、stale dream_id。
- Tauri command bridge focused test/静态检查，确认 `dream_id` 请求与响应字段没有被丢弃。
- 后端使用项目约定 Python 入口运行指定 Dream tests，带 `-n auto`；桌面运行相关 Vitest、
  `npx.cmd tsc --noEmit` 和 `npm.cmd run build`。
- 跨进程 E2E 必测：真实启动 backend + desktop，完成“入梦 → 触发挽留 → 仍然醒来 → DreamWindow 关闭 →
  重开只见 ready/archive replay → 旧梦无法发送 → 新入梦 ID 不同”。只跑 mocked unit tests 不得宣称本 Brief
  完成。
- `git diff --check`；检查未修改真实 `data/runtime`、`userdata`、角色卡或用户 Dream settings。

## 不在范围内

- 不删除软挽留，不删除“留下”，不把首次 WAKE 无条件改成 hard exit。
- 不改变挽留的情绪/轮数门槛、挽留文案生成 Prompt 或 LLM 路由，除非修复所需的最小 session identity 接线。
- 不修改 Dream Scenario 推进、全量导演模式、语义 reconciler、private truths 或角色行为策略。
- 不改变 Reality continuation 的 Prompt/记忆边界，不把 Dream archive 注入 Reality。
- 不扩展 Group Dream 软挽留，不改手机 Dream 产品面。
- 不迁移、删除或覆盖真实 Dream archive/current 数据；生产残留只通过正常 close contract 收口。
- 不把 archive replay 重新接到 live pipeline、WS、TTS、伪流式或 current-session writer。

## 建议施工顺序与独立提交边界

1. 后端 WAKE 状态分类、exit metadata、dream_id guard 与 focused 状态/文件测试，独立 backend commit。
2. 客户端/Tauri retention session identity、确认醒来、错误处理和纯逻辑 tests，独立 desktop commit。
3. archive replay/新梦隔离回归、运维观测和文档同步，按仓库拆分独立 commit。
4. backend + desktop 跨进程 E2E，记录真实证据并收口工单状态；若 E2E 未跑只能标记 `partial`。

每一步相关测试与差异检查完成后立即提交。不得用“窗口已经关闭”代替“后端已 archive 且旧梦不可继续”的
验收，也不得用“resume 还能工作”证明退出路径正确。
