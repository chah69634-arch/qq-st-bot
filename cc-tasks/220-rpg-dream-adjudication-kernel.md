# Brief 220：跑团确定性裁定、知识投影与骰点内核

> 状态：`blocked-by-219`
>
> 前置：Brief 219 已完成并独立提交
>
> 后续：Brief 221

## 一、目标

在不调用 LLM 的前提下，实现 RPG session 的确定性领域内核：append-only 世界事件、三方知识投影、可审计骰点、派生场景快照和纠正/分支原语。

本单只接受结构化 `KpProposal` 测试输入；不解析自然语言，不接角色卡，不开放用户可玩的 turn endpoint。

## 二、开工前必读

- Brief 219 的提交与测试结果
- `docs/rpg-dream-mode-design.md`
- `docs/dream.md`
- `docs/runtime-lifecycle.md`
- `docs/interaction-event-model.md`
- `docs/security_model.md`
- `docs/dev-environment.md`

## 三、领域契约

### 3.1 事件与投影

每次状态变化先形成一个不可变事件，再派生展示/角色视图：

```text
RpgEvent
  event_id / dream_id / round_id / branch_id / seq / ts
  event_type
  causation_id
  payload (typed by event_type)
  projections:
    public
    player
    character
    kp_private
```

事件 ID、seq、branch 与 causation 必须由后端生成/校验。客户端或 LLM 不能提交 owner、char、realm、路径或写权限字段。

角色知识使用稳定 `fact_id` 和状态：`unknown | suspected | known | misbelieved`。公开不可逆：已经进入 `public`/`character` 投影的事实不能被普通后续事件静默隐藏；纠正只能 append 新事件。

### 3.2 KP proposal

定义严格 schema，`extra=forbid`。KP 只能提出：

```text
decision = automatic_success | automatic_failure | roll | reject
check_type / reason_code
roll_spec? = dice_count, dice_sides, modifier, dc
outcome_branches = 每个可能结果对应的 typed effects/projections
scene_updates
character_should_respond
```

自由文本必须有长度上限；引用只能指向当前 scene/stage 的安全 ID。proposal 不是事实，只有内核验证通过并 `apply` 后才写事件。

### 3.3 骰点

- 第一版只允许有界 `NdM + modifier vs DC`，具体上限由常量与测试冻结；拒绝任意表达式解析和代码求值。
- seed/nonce、原始骰面、修正、DC、总值、结果桶、proposal digest 写 `dice.jsonl`；使用 `safe_append_jsonl`。
- seed 与骰面只能由后端产生；客户端、KP LLM 和角色不能指定或覆盖。
- KP 在骰点前必须提交全部结果分支；内核掷骰后只选择对应分支，禁止二次改写既定后果。
- 支持 `critical_failure/failure/success_with_cost/success/critical_success`；自动结果同样产生统一 resolution event，但不伪造骰点记录。

### 3.4 快照

从事件 ledger 派生：

- shared scene/base facts；
- player-known facts；
- character knowledge/beliefs；
- KP full state；
- 当前 branch/revision/cursor。

快照可缓存但不是第二事实源。缓存损坏时从当前 branch 的事件重建；不得读取其他 dream、uid 或 char 的账本。

## 四、纠正与分支原语

实现内部命令：

- `clarify(target_round_id, text)`：补充解释，不撤销事件。
- `retcon(target_round_id, reason)`：append 撤销标记并从目标前一 revision 派生新 branch。
- `branch(target_round_id, reason)`：保留旧 branch，只切换 active branch。

已落盘骰点永不删除或覆盖；旧 branch 不再进入当前角色/KP prompt，但保留审计与回放。所有命令要求当前 `dream_id`、预期 revision 和幂等 `request_id`，CAS 失败返回稳定 conflict。

## 五、存储与观测

使用 Brief 219 注册的路径，不新增硬编码 `data/` 路径。ledger 追加与 session revision 更新需要明确的提交顺序；崩溃恢复不得重复掷骰。若无法做到跨文件原子事务，使用 pending/committed receipt 并通过幂等 request ID 恢复，不能靠“再掷一次”。

扩展 `/observability/dream-rpg`，仅增加事件/骰点/branch 数量、恢复/冲突/非法 proposal 计数和延迟桶，不返回正文、DC、seed、骰面或隐藏事实。

## 六、建议文件

- `core/dream/rpg_events.py`
- `core/dream/rpg_projection.py`
- `core/dream/rpg_dice.py`
- `core/dream/rpg_engine.py`
- `core/dream/rpg_corrections.py`
- `tests/test_dream_rpg_engine.py`
- `tests/test_dream_rpg_dice.py`
- `tests/test_dream_rpg_projection.py`

## 七、测试

至少覆盖：

1. 五种结果桶与 auto success/failure/reject。
2. 非法骰式、越界 DC/modifier、额外字段、跨 session ID 全部 fail-closed。
3. 相同 seed fixture 可重放，相同 request ID 不重复掷骰；崩溃恢复不产生第二结果。
4. KP proposal 在掷骰前已冻结所有 outcome branches。
5. public/player/character/KP 四投影无越权泄漏。
6. `unknown/suspected/known/misbelieved` 转换和公开不可逆。
7. snapshot rebuild 与在线派生一致。
8. clarify/retcon/branch append-only，旧骰点保留，新 branch cursor 正确。
9. 并发 revision/CAS 冲突稳定，不丢事件、不交叉 uid/char/dream。
10. Reality memory、ordinary tool loop、stimulus、afterglow 均零调用。
11. 观测投影不含正文、seed、骰面、DC 或绝对路径。

```powershell
pytest -n auto tests/test_dream_rpg_engine.py tests/test_dream_rpg_dice.py tests/test_dream_rpg_projection.py tests/test_dream_rpg_foundation.py tests/test_dream_isolation_guard.py tests/test_data_root_isolation.py
```

## 八、非目标

- 不调用 KP/角色模型。
- 不解析 `<C>`。
- 不做桌面双栏或 WS 帧。
- 不新增规则书解析、D&D 角色卡或复杂骰池语言。
- 不把 RPG ledger 接入 Memory Event Ledger。

## 九、验收与提交

确定性内核、恢复、观测和隔离测试通过；差异检查完成后立即创建独立 Git commit，再开始 Brief 221。

