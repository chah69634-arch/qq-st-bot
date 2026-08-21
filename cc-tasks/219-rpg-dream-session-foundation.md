# Brief 219：跑团 Dream Session 基座与生命周期

> 状态：`ready`
>
> 依赖：设计决策 `docs/rpg-dream-mode-design.md`
>
> 后续：Brief 220 → 221 → 222；完成本单并独立提交后再开 220

## 一、目标

为单人 Dream 增加第四种 `dream_mode="rpg"` 的最小 session 基座，冻结生命周期、数据路径、能力发现和安全状态投影。本单不调用 KP/角色 LLM，不掷骰，也不实现可玩的回合。

第一版参与者固定为：一个用户、当前 active 角色卡对应的一个主要 AI 角色、一个纯旁白 KP。`rpg` 复用现有 Scenario authored script（`script_id` 必填），不在本单新增第二套剧本格式。

## 二、开工前必读

- `AGENTS.md`
- `DESIGN.md`
- `ARCHITECTURE.md`
- `docs/dream.md`
- `docs/rpg-dream-mode-design.md`
- `docs/runtime-lifecycle.md`
- `docs/interaction-event-model.md`
- `docs/security_model.md`
- `docs/dev-environment.md`
- `docs/three-repo-interface-catalog.md`

## 三、生命周期契约

1. `/dream/enter` 接受 `dream_mode="rpg"`，要求合法 `script_id`，冻结 `char_id/script_id/dream_id/mode`，整场不得切换。
2. 与 sandbox/scenario/mirror、单人梦和 Group Dream 双向互斥；继续使用 owner conversation lock 与现有 Dream Guard。
3. `/dream/chat` 遇到活跃 RPG session 必须返回稳定 409：

```json
{"detail":{"code":"RPG_ENDPOINT_REQUIRED","message":"...","retryable":false}}
```

不得把 RPG 输入降级送入普通 dream pipeline。
4. `/dream/exit` 仍是无条件、立即、幂等的 hard exit；不得增加 KP/角色 LLM 调用后才退出。
5. `/dream/wake`、`/dream/resume` 沿用现有 Dream 状态机；RPG 与 Scenario 一样不写 afterglow、impression、hidden state 或 Reality continuation。
6. 进程重启后以落盘 state 恢复真值；半写 session fail-closed 为 `uncertain`，不伪造可继续状态。

## 四、模型与路径

新增冻结 dataclass/Pydantic domain model（命名可按代码调整）：

```text
RpgCore
  schema_version
  dream_id / script_id / owner_uid / char_id
  status
  active_branch_id
  active_round_id / round_status
  next_round_seq / next_event_seq
  scene_revision
  created_at / updated_at
  last_error_code
```

`RpgCore` 不保存 prompt、用户正文、KP 私密正文、token 或模型原始响应。

所有新路径必须通过 `core/sandbox.get_paths()`，并同步 `core/data_registry.REGISTRY`。建议每场物理隔离：

```text
data/runtime/dreams/{char_id}/rpg/{uid}/{dream_id}/
  session.json
  events.jsonl          # 220 才写领域事件
  dice.jsonl            # 220 才写骰点审计
  transcript.jsonl      # 221 才写双栏展示记录
```

本单只创建必要目录和 `session.json`，不得预写空账本冒充事件。写入使用原子写；关闭时按现有 Dream archive 语义归档或标终态，不能把活跃目录留成第二个真值源。

## 五、后端能力与状态接口

新增 typed response，禁止继续用无约束 `dict` 扩散新协议：

### `GET /dream/capabilities`（`activity`）

返回至少：

```json
{
  "supported_modes":["sandbox","scenario","mirror","rpg"],
  "rpg":{"available":true,"contract_version":"rpg/v1","max_primary_characters":1}
}
```

能力来自实际后端代码，不受客户端偏好伪造。

### `GET /dream/rpg/state`（`activity`）

返回活跃/最近 session 的安全投影：`dream_id/char_id/script_id/status/round_status/active_round_id/active_branch_id/scene_revision/since/last_error_code`。不返回世界秘密、正文、prompt、骰点 seed 或角色卡全文。

### `GET /observability/dream-rpg`（`state.read`）

新增落盘状态同单提供只读观测。只返回 session/round 计数、状态、错误码、恢复来源、最近时间和路径健康码；ID hash/truncate，不返回正文或绝对路径。

## 六、实现边界

建议新增：

- `core/dream/rpg_models.py`
- `core/dream/rpg_store.py`
- `core/dream/rpg_state.py`
- `admin/routers/dream_rpg.py`
- 对应 tests

按需最小修改：

- `core/dream/dream_pipeline.py`
- `core/dream/dream_state.py`
- `core/data_paths.py` / `core/data_registry.py`
- `admin/admin_server.py`
- `admin/routers/dream.py`

禁止把 RPG 做成 `main.py` 或普通 Pipeline 的新分支；它必须是 Dream 内显式 Session 子域。

## 七、测试

至少覆盖：

1. `rpg` 合法入场且 `script_id` 必填/存在；其他三模式零回归。
2. mid-session 换 mode、换 script、换 char 均 fail-loud。
3. 单梦/群梦互斥、conversation lock、重入幂等。
4. `/dream/chat` 在 RPG 活跃时稳定返回 `RPG_ENDPOINT_REQUIRED`，不调用普通 dream turn。
5. hard exit 不调用 LLM，重复退出不重复归档。
6. RPG 不写 afterglow/impression/Reality memory/continuation。
7. corrupt/missing/half-written state 的恢复和 fail-closed 行为。
8. 新路径注册、test sandbox 隔离、观测端点不泄露正文/绝对路径。
9. capabilities 与实际 mode enum 一致，scope 扫描通过。

建议命令：

```powershell
pytest -n auto tests/test_dream_rpg_foundation.py tests/test_dream_scenario_session.py tests/test_dream_exit_contract.py tests/test_dream_exit_idempotency.py tests/test_dream_isolation_guard.py tests/test_data_registry.py tests/test_sec_auth2_scopes.py
```

## 八、文档与闭环

同步 `docs/dream.md`、`docs/security.md`、`docs/three-repo-interface-catalog.md`、`docs/data-taxonomy.md`。桌面/手机尚不消费，必须在总账标 `open: backend foundation only`，不得写成功能完成。

## 九、验收与提交

- 生命周期、typed API、安全状态投影、路径注册和观测同单完成。
- 未新增 LLM 路由、骰点、角色生成或客户端代码。
- 相关测试与 `git diff --check` 通过。
- 差异检查完成后立即创建独立 Git commit，再开始 Brief 220。

