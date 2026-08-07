# 150 Dream 阻断混合 opportunity 时保留非 wake 信号

## 背景

Brief 149 将 `desktop_wake` Path B 迁移到了 signal-first autonomy。`desktop_wake` 是一次性
reopen 事实：入队后若再次被 Dream Guard 阻断，不应在出梦后补发。

当前 `core/autonomy/runner.py::tick()` 用以下 job 级条件控制 Dream 阻断重试：

```python
retry_dream_block = (
    run.disposition in {"blocked_dream", "blocked_dream_uncertain"}
    and "desktop_wake" not in set(job.signal_sources or [])
)
```

但 runner 会把同一窗口内的 `desktop_wake`、scheduler、sensor、memory 等信号合并为一个
opportunity。只要混合 job 中含 `desktop_wake`，上述条件就会把整个 job 标记为完成，连同本应
保留的 `hr_critical`、其他 sensor 或普通 scheduler 信号一起丢弃。

简单改成“只有 `signal_sources == {"desktop_wake"}` 才禁用重试”也不正确：它会让混合 job
中的一次性 wake 随其他信号一起在出梦后重放。

## 目标

Dream Guard 阻断混合 opportunity 时：

- `desktop_wake` 作为一次性事实终态结束，不重试；
- 仍在 TTL 内的非 wake 信号被保留并形成一个新的有界 retry job；
- 过期信号得到明确的 terminal outcome；
- 不重复执行原 job、不重复 wake、不丢失高优先级非 wake 信号；
- parent run、wake 终态与 child retry job 均可通过现有 autonomy 观测解释。

## 实施要求

### A. 按 signal 拆分 Dream retry

1. 在 `run_job()` 返回 `blocked_dream` / `blocked_dream_uncertain` 后，从
   `job.opportunity["signals"]` 恢复并校验 `Signal` 对象。
2. 将信号拆为：
   - one-shot：当前至少包括 `source="desktop_wake"`；
   - retryable：其余现有信号，沿用迁移前 Dream 阻断可重试语义。
3. parent job 必须完成并记录本次 Dream-blocked run，不能继续把原混合 job 整体设回 pending。
4. one-shot wake 不进入 child job。其终态可记录在 parent run 的有界 event 中，或复用既有
   signal outcome 结构，但不能新增无观测台账。
5. 对 retryable 信号重新检查原始 `expires_at`：
   - 尚未过期：合并为一个 child opportunity 并入队；
   - 已过期：记录 `expired` terminal outcome，不进入 child job。
6. child job 的 TTL 不得超过剩余最短 signal TTL，dedupe key 必须稳定关联 parent job/run，避免
   同一 Dream-blocked attempt 重复创建 child job。

### B. 状态一致性

parent finish 与 child enqueue 不应由两个无保护的 read-modify-write 互相覆盖。优先在
`core/autonomy/store.py` 增加一个窄用途 helper，在同一次 state load/save 中完成：

- 校验 parent lease token；
- parent job 标记 done；
- append parent run；
- append 去掉 one-shot 信号后的 child job（若有）；
- 更新必要的 bounded source/daily/circuit 状态。

不要通过调用现有 `finish()` 后再独立调用 `enqueue_opportunity()` 拼接事务；当前 JSON store 没有
跨调用事务，这会在并发 tick、配置更新或其他 signal enqueue 时产生丢更新风险。

若实现选择引入锁，必须复用项目既有 scoped lock/原子写模式，不新增全局粗锁，也不得在持锁期间
await LLM、网络或 channel send。

### C. 语义边界

- 纯 `desktop_wake` job 遇到 Dream 阻断：维持 Brief 149 行为，完成且不重试。
- 不含 `desktop_wake` 的 job：维持原有 Dream retry 行为，不做额外拆分。
- 混合 job：仅 non-wake 子集重试；wake 永不进入 child opportunity。
- 不根据 priority 猜测是否保留；只要是现有可重试的 non-wake signal 且未过期，就必须保留。
- 不改变普通 user chat、Path A 历史回放、工具路径、talk gate 或 Dream Guard 判定本身。

## 验收测试

使用 `pytest -n auto` 跑相关测试，至少覆盖：

1. 纯 wake opportunity 被 Dream 阻断后 parent done、无 child job、无未来补发。
2. 纯 non-wake opportunity 被 Dream 阻断后保持现有 bounded retry 行为。
3. `desktop_wake + hr_critical` 混合 opportunity 被 Dream 阻断后：
   - parent job done；
   - wake 只出现于 parent，未进入 child；
   - child 只含 `hr_critical`，Dream 解除后可正常被 claim；
   - 最终最多一次用户可见 Talk。
4. `desktop_wake + scheduler + sensor` 混合机会只创建一个过滤后的 child job，不按 signal
   创建多个并行 job。
5. 混合机会中部分 non-wake signal 已过期时，仅保留仍有效者；全部过期时不创建 child，并为
   过期项留下 terminal observation。
6. 重复调用 finish/split helper、lease token 失效或 worker 重领后，不重复创建 child job，也不
   覆盖新 worker 的状态。
7. 并发 enqueue 新 signal 时不丢失既有 pending signal、parent run 或 child job。
8. autonomy opportunity/run 观测能关联 parent blocked run 和 child retry job，并明确显示
   `desktop_wake` 未被重放。

## 可能涉及文件

- `core/autonomy/runner.py`
- `core/autonomy/store.py`
- `core/autonomy/models.py`（仅在确有必要补 retry lineage 字段时）
- `tests/test_desktop_wake_autonomy.py`
- `tests/test_autonomy.py`
- `docs/autonomy.md`
- `docs/scheduler.md`

## 非目标

- 不重新设计 autonomy store 或引入数据库。
- 不让 `desktop_wake` 恢复为可重试信号。
- 不改变 Dream session 生命周期或出梦触发器。
- 不把 signal 拆分逻辑放进 HTTP `/desktop/wake` handler。

## 施工前必读

- `AGENTS.md`
- `docs/dev-environment.md`
- `docs/runtime-lifecycle.md`
- `docs/interaction-event-model.md`
- `docs/security_model.md`
- `docs/scheduler.md`
- `docs/autonomy.md`
- `cc-tasks/149-retire-desktop-wake-path-b-direct-turn.md`
