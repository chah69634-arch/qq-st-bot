# 224 · Autonomy admission：stale activity + 预算记账根治

> 状态：实施中（2026-08-27）  
> 范围：运维急救（可回传数据）+ 代码根治；不恢复 `_pipeline_send`，不抬随机开口概率。

## 一、现场证据（yexuan / `<owner_uid>`）

拉回 `data/runtime/autonomy/yexuan/<owner_uid>/state.json`：

- `config.enabled=true`，`talk_enabled=true`
- `daily.evaluations=266`，`daily.talks=0`（预算默认 12）
- 留存 runs 100/100：`evaluation_status=blocked_or_failed`，`disposition=blocked_user_active`
- jobs 仍在合并高价值信号：`dream_exit` + `topic_followup` + `spontaneous_recall`（约每 60s）

卡死会话：

`data/runtime/activity/yexuan/<owner_uid>/dream_seed/<session_id>/session.json`  
`status=active` 自 2026-08-06，从未关闭。

根因链：

1. `policy.admission()` 对任意 `find_active_session(...)` 返回 `blocked_user_active`
2. `dream_seed.close_session()` 在 transcript < 2 或蒸馏/保存失败时直接 `return None`，**不**调用 `store.close_session` → 僵尸 active
3. `store._update_finish_counters()` 对 admission-only 失败仍 `evaluations += 1` 且写 `sources.*.last_evaluated_at` → 打爆预算 + 跨 source `duplicate` 冷却

## 二、步骤

### A. 运维急救（本机数据，回传服务器）

1. 关闭上述 dream_seed session（`closed` + `closed_at`）
2. 重置当日 `daily.evaluations/tools/talks = 0`（保留 `day`；保留 runs 对照）

### B. 代码

1. `ActivityMeta` 增加 per-type `idle_ttl_seconds` / `max_age_seconds`；`find_active_session` lazy-expire
2. dream_seed 放弃/失败关闭也必须 close session；聊天路径刷新 `updated_at`
3. admission-only disposition 不计 `evaluations`、不推进 `last_evaluated_at`（可记 `last_attempt_at`）
4. `talks == 0` 时跳过 daily evaluation budget 门（其他门不变）；`effective_state` 对齐

### C. TTL

| type | idle | hard max |
|---|---|---|
| dream_seed | 12h | 24h |
| gomoku / chess | 72h | 7d |
| reading | 7d | 14d |

## 三、验收

- `find_active_session(yexuan, <owner_uid>, dream_seed) is None`
- 相关 pytest 通过（含翻转短 close 预期）
- 部署后观测：`blocked_user_active` 下降；出现真实 `evaluated_silent` 或 `talk_sent`；若仍长期 `talks=0` 再单开模型决策校准，不再猜供给/admission
