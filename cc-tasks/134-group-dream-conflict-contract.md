# Brief 134: 群梦结构化冲突、原子入场与客户端诊断

来源：2026-08-04 群聊梦境入场只显示“当前状态无法进入梦境（HTTP 409）”的跨仓审计。

## 目标

让群梦入场冲突具备稳定、可观测、可恢复的契约：后端返回结构化冲突码，客户端保留具体原因并对“已经入梦”进行状态接续；同时消除仅检查 `conversation_lock.locked()` 带来的检查与执行竞争窗口。

## 已确认根因

后端 `/group/{id}/dream/enter` 当前可能因以下原因返回 409：

- 本群已有活跃群梦
- owner 正在单人梦境
- owner 的 conversation lock 正被占用
- 群 domain 非 reality

后端 detail 含具体文本，但 desktop Rust bridge 只解析 401/403 body；其他状态码统一压缩为 `HTTP <status>`，导致 UI 丢失根因。入场拒绝没有独立审计，事后无法判断当时命中了哪一条。当前实现还只是观察 `conversation_lock.locked()`，随后异步构建快照并写状态，存在 TOCTOU 窗口。

## 实现要求

### 1. 稳定的结构化冲突码

群梦入口的预期冲突必须返回统一 shape，例如：

```json
{
  "detail": {
    "code": "OWNER_CONVERSATION_BUSY",
    "message": "该 owner 当前有对话正在处理，请稍后重试",
    "retryable": true
  }
}
```

至少定义：

```text
GROUP_NOT_REALITY
GROUP_DREAM_ALREADY_ACTIVE
SOLO_DREAM_ACTIVE
OWNER_CONVERSATION_BUSY
GROUP_DREAM_ENTERING
GROUP_DREAM_STATE_UNCERTAIN
```

错误码是跨仓契约；message 用于展示但不得作为客户端分支判断依据。不得在响应中泄露 owner uid、路径、锁对象、快照内容或异常堆栈。

### 2. 原子 transition reservation

不要用“检查 `conversation_lock.locked()` 后继续执行”作为入场互斥。

为 group dream lifecycle 引入独立、进程内的 transition lock/reservation，满足：

1. 同一 group 的并发 enter 只有一个能预占
2. 预占后状态可投影为 `ENTERING` 或等价内部 transition 状态
3. 快照构建失败时释放 reservation，并恢复到可重试状态
4. 成功写入 `DREAM_ACTIVE` 后释放 transition lock
5. exit 与 enter 不得并发破坏同一 state
6. 不持有全局锁

若 `DreamStatus` 冻结契约不适合新增持久化枚举，可将 `ENTERING` 保持为进程内 reservation，并由 state endpoint 返回独立 `transition` 字段；必须说明重启时如何自然恢复。不要写一个无法从崩溃恢复的持久化半状态。

conversation lock 仍用于判断现实对话是否正在处理，但“判断 + reservation”必须有明确顺序和测试。不得长时间持有 conversation lock 去包围潜在 LLM/网络调用。

### 3. 入场审计

新增群梦 transition audit，记录：

- timestamp
- group_id
- action=`enter|exit`
- result=`accepted|rejected|failed`
- conflict/error code
- 当时的安全状态枚举：group dream status、solo dream status、conversation busy、transition busy
- dream_id（成功时）

不得记录 transcript、entry_reason 正文、snapshot、用户消息、角色卡、owner uid 明文或异常堆栈。

按照 AGENTS.md，新增落盘台账必须提供只读观测端点。建议在既有 group router 下提供：

```text
GET /group/{id}/dream/transition-audit?limit=
```

scope 使用 `state.read`；限制分页、最大 limit，并保持 group 存在性校验。

### 4. Desktop HTTP 错误透传

`Emerald-client` 的 Rust bridge 必须安全解析所有预期 4xx 的结构化 detail，而不是只处理 401/403。

要求：

- 保留 status、code、message、retryable
- 401/403/429 现有安全语义不回归
- 5xx 不向 WebView 透传任意上游正文或堆栈
- TypeScript 使用 code 分类，不解析中文 message

可以扩展现有 `classifyHttpError()` 返回结构，或建立统一 IPC error shape；不得只为 DreamWindow 写字符串正则特例。

### 5. 客户端恢复行为

- `GROUP_DREAM_ALREADY_ACTIVE`：立即 refresh state；若状态确实 active，接续已有梦并切换到 active UI，不显示失败
- `OWNER_CONVERSATION_BUSY` / `GROUP_DREAM_ENTERING`：保留 ready UI，显示可重试文案，不自动无限重试
- `SOLO_DREAM_ACTIVE`：明确提示先退出单人梦
- `GROUP_NOT_REALITY` / `STATE_UNCERTAIN`：显示不可直接重试的诊断文案
- 409 后必须 refresh 一次 state，避免 UI 与后端状态长期分叉

新增或修改的用户可见文案必须走 `src/shared/i18n/`。

### 6. 文档与协议

同步：

- `docs/stage.md`
- `docs/channels.md`（若 IPC/HTTP error shape 被记录在此）
- desktop `docs/backend-integration.md`
- desktop `docs/dream-hud.md`
- 对应 API/契约测试

本 Brief 修改的是 HTTP 错误契约，不新增桌面 WS action，也不改变 v0.1 WS 消息全集。

## 相关文件

后端：

- `admin/routers/group_dream.py`
- `core/stage/dream_state.py`
- 新增集中 transition guard/audit 模块（如确有必要）
- `admin/scopes.py`（仅当路由 scope 注册方式需要）
- `docs/stage.md`
- `tests/test_dream_stage.py`
- 新增 transition concurrency/audit 测试

Desktop：

- `src-tauri/src/lib.rs`
- `src/shared/api/httpError.ts`
- `src/shared/api/httpError.test.ts`
- `src/windows/dream/DreamWindow.tsx`
- `src/shared/i18n/locales/zh-CN.ts`
- `src/shared/i18n/locales/en-US.ts`
- `docs/backend-integration.md`
- `docs/dream-hud.md`

## 测试

至少覆盖：

1. 每个冲突条件返回稳定 code/message/retryable
2. 响应不泄露 uid、路径、snapshot 或堆栈
3. 两个并发 enter 只有一个成功预占
4. snapshot 构建失败后 reservation 被释放，可再次 enter
5. enter/exit 并发不会产生损坏状态
6. conversation busy 与 transition busy 可区分
7. accepted/rejected/failed 均写 transition audit
8. audit endpoint 的 scope、分页、limit 与不存在 group 行为正确
9. audit 内容不包含 entry_reason/transcript/snapshot/owner uid
10. desktop Rust 保留结构化 409 detail
11. 401/403/429 既有错误分类不回归
12. 5xx 不透传任意后端正文
13. `ALREADY_ACTIVE` 刷新后接续 active UI
14. retryable 与 non-retryable 冲突展示不同 i18n 文案
15. 409 后执行一次 state refresh

后端使用并行 pytest 跑相关测试。Desktop 至少运行：

```text
npm test
npx.cmd tsc --noEmit
npm.cmd run build
cargo check
```

## 非目标

- 不改变群梦零回流、hard_exit、card_only 等既有边界
- 不把 group dream 合并进单人 dream state 文件
- 不持久化用户 entry_reason 或 snapshot 到审计
- 不自动退出单人梦
- 不无限自动重试 enter
- 不升级桌面 WS v0.1

## 验收

- 用户不再只看到无信息量的 `HTTP 409`
- `ALREADY_ACTIVE` 可以恢复并接续，而不是误报失败
- 并发 enter/exit 不产生重复 dream 或损坏状态
- 每次拒绝都能从只读审计端点确认具体原因
- 后端相关测试并行通过
- Desktop test、TypeScript、Vite build、Rust check 通过
- 两仓分别 `git diff --check` 通过
- 后端与 Desktop 各自独立 commit，并在工单中回填双方 hash
