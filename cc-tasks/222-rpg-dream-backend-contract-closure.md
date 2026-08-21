# Brief 222：跑团后端接口闭环、回放与前端交接

> 状态：`blocked-by-221`
>
> 前置：Brief 219、220、221 已完成并各自独立提交
>
> 本单完成后才允许编写桌面双栏前端工单

## 一、目标

把 RPG 后端从“能跑一轮”收口为客户端可依赖的完整 v1 合同：活动记录恢复、纠正接口、归档回放、能力/错误码、scope、管理面只读观测、OpenAPI 和三仓接口文档一致。

本单不实现 Emerald-client 双栏，也不新增 mobile UI。

## 二、开工前必读

- Brief 219-221 的提交与测试结果
- `docs/rpg-dream-mode-design.md`
- `docs/dream.md`
- `docs/channels.md`
- `docs/security.md`
- `docs/three-repo-interface-catalog.md`
- `docs/feature-control-surface.md`
- `docs/dev-environment.md`

## 三、冻结的 v1 REST 清单

所有请求/响应必须是 Pydantic typed schema，`extra=forbid`；精确 schema 最终以 `/openapi.json` 为准。

| 方法 | 路径 | scope | 用途 |
|---|---|---|---|
| GET | `/dream/capabilities` | `activity` | modes、`rpg/v1`、硬上限 |
| POST | `/dream/enter` | `activity` | `dream_mode=rpg + script_id` 入场 |
| GET | `/dream/rpg/state` | `activity` | 活跃 session/round/shared scene 安全投影 |
| POST | `/dream/rpg/turn` | `activity` | character/kp lane 幂等回合 |
| GET | `/dream/rpg/transcript` | `activity` | 活跃场双栏分页恢复 |
| POST | `/dream/rpg/corrections` | `activity` | clarify/retcon/branch |
| GET | `/dream/archive` | `activity` | 含 RPG archive 元数据 |
| GET | `/dream/archive/{dream_id}` | `activity` | RPG 玩家可见回放，保留 lane/kind/correlation |
| GET | `/observability/dream-rpg` | `state.read` | metadata-only 运行观测 |
| POST | `/dream/exit` | `activity` | 现有无条件 hard exit，保持不变 |

`/dream/rpg/state` 可返回当前 shared scene/base facts，但不能返回 KP private、角色卡全文、prompt、seed、隐藏 DC 或未选中分支。`transcript/archive` 只返回用户在游戏时本就可见的 character/KP/shared 三栏内容。

## 四、分页、恢复与纠正接口

### Transcript

`GET /dream/rpg/transcript?dream_id=&before=&limit=`：稳定按 event/entry cursor 分页，默认/最大 limit 固定；返回 `items/next_before/has_more/scene_revision/active_branch_id`。单条损坏允许 `partial_read=true`，不得令整场不可恢复，也不得跨 dream 读取。

### Corrections

请求至少包含：

```json
{
  "dream_id":"...",
  "request_id":"...",
  "operation":"clarify|retcon|branch",
  "target_round_id":"...",
  "text":"...",
  "reason":"...",
  "expected_scene_revision":4
}
```

clarify 不重掷；retcon/branch 不删除旧事件/骰点。响应返回新 branch/revision 和玩家可见控制 entry。跨梦、过期 revision、已关闭场和重复 ID 均使用稳定错误码。

## 五、错误码与并发合同

至少冻结：

```text
RPG_NOT_ACTIVE
RPG_ENDPOINT_REQUIRED
RPG_DREAM_ID_MISMATCH
RPG_ROUND_BUSY
RPG_IDEMPOTENCY_CONFLICT
RPG_REVISION_CONFLICT
RPG_INVALID_LANE
RPG_INVALID_CORRECTION
RPG_KP_UNAVAILABLE
RPG_KP_OUTPUT_INVALID
RPG_CHARACTER_GENERATION_FAILED
RPG_SESSION_UNCERTAIN
```

错误 shape 统一 `{detail:{code,message,retryable,round_id?}}`；客户端按 code 分支，不解析中文 message。hard exit 永不因上述错误被阻塞。

## 六、归档与数据保留

- 退出时封存 RPG 玩家可见 transcript、session metadata、branch/revision 和 completion；archive 失败保留可恢复 closing 状态，不伪报关闭成功。
- KP hidden ledger/dice audit 与玩家回放物理/逻辑隔离；普通 archive endpoint 不返回 seed、未选中分支或 KP private facts。
- archive 只读，不重新挂载 session、不调用模型、不广播、不写 Reality memory。
- 数据路径、retention/cap 与 `core/data_registry` 治理说明同步；删除/清理策略不能让 archive 引用悬空。

## 七、管理面与三面闭环

在本仓 admin 管理面增加只读 RPG 运行摘要：能力、活跃状态、round/branch/dice 计数、最近稳定错误码和隔离健康；不展示正文、隐藏事实、DC/seed/骰面或 prompt。修改 page fragment/JS/CSS 时按 Admin Static Asset Cache 规则更新版本。

闭环结论：

- Backend/admin：接口、scope、effective capability、观测、审计、归档齐全。
- Desktop：仍为 `open`，后续工单消费本单 OpenAPI，不猜字段。
- Mobile：v1 不消费；现有 Dream mode 列表若遇未知 `rpg` 必须保持兼容，未验证项记 `open`。
- 原路径：sandbox/scenario/mirror、Group Dream、hard exit、Reality Guard、普通 chat/WS/TTS 均不受影响。

## 八、OpenAPI 与接口交接产物

新增 `docs/rpg-dream-api.md`，记录：

- v1 endpoint/flow；
- 请求响应示例（只用占位 ID，不含真实用户/角色名）；
- error code 与 retry 策略；
- lane/entry kind 枚举；
- idempotency/revision/round lock；
- capability detection；
- 客户端不得读取 runtime 文件或依赖未声明 WS 帧。

从测试 app 的 `/openapi.json` 断言所有 schema/ref/required 字段，不手写一套与 OpenAPI 漂移的“精确 schema”。同步 `docs/dream.md`、`docs/security.md`、`docs/feature-control-surface.md`、`docs/three-repo-interface-catalog.md`、`docs/known-issues.md`。

## 九、测试

至少覆盖：

1. REST 清单、method、scope、typed request/response 与 OpenAPI required/enum。
2. transcript 分页稳定、branch 过滤、partial read、跨 dream 拒绝。
3. corrections 三操作、幂等、revision conflict、关闭场拒绝、旧骰点保留。
4. 退出归档、archive failure recovery、重复退出、回放只读。
5. 所有稳定错误码与 retryable 值。
6. capabilities 与实际 router/mode/limits 一致。
7. admin 只读观测及静态资源缓存版本；写接口 coverage 无遗漏。
8. desktop/mobile token scope 不扩大，KP private/seed/prompt/绝对路径泄漏扫描。
9. sandbox/scenario/mirror/Group Dream/Reality Guard/普通 Dream archive 回归。
10. 端到端：两 lane 各一轮、一次角色 `<C>`、一次骰点、一次 correction、退出、回放。

```powershell
pytest -n auto tests/test_dream_rpg_api.py tests/test_dream_rpg_archive.py tests/test_dream_rpg_corrections.py tests/test_dream_rpg_runtime.py tests/test_dream_rpg_security.py tests/test_dream_archive_operations.py tests/test_dream_exit_contract.py tests/test_dream_isolation_guard.py tests/test_dream_stage.py tests/test_sec_auth2_scopes.py tests/test_admin_ui_route_coverage.py
```

实现者还需导出/读取测试 app 的 `/openapi.json` 完成字段核对。只跑相关测试，不默认跑无关全量；若跑全量必须 `pytest -n auto`。

## 十、验收与提交

- 完整 REST、状态恢复、纠正、回放、观测、scope、OpenAPI 和文档闭环。
- 后端端到端测试证明接口足够支持双栏客户端。
- `docs/known-issues.md` 明确桌面双栏仍为 `open`，不得宣称前端完成。
- 相关测试、`git diff --check`、敏感信息扫描通过。
- 完成后立即创建独立 Git commit；随后才编写桌面前端工单。

