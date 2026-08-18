# Brief 216 · MER-11 · Memory Event 最终边界修正与控制面观测收口

> 状态：completed（代码）/ deployment pending
> 依赖：MER-10（`ed8f97c`）
> 施工方式：单张一次性工单；先只读核对，再实现、验证、独立提交
> 范围：只修代码、测试、管理面与文档，不自动迁移服务器历史数据

## 1. 目标

在不改变 Memory Event 总体架构、不改变默认召回行为的前提下，收掉 MER-10
复核发现的四个确定性问题，并把 shadow recall 与 relation proposer 的控制面、
生效状态和运行观测接完整。

本工单不是重新设计事件账本，也不是执行历史数据迁移。迁移仍然必须由维护者
在服务器上先执行只读 dry-run、核对报告并确认快照后，另行决定是否 apply。

## 2. 两个功能的准确边界

### 2.1 Shadow recall

shadow recall 是后台诊断路径：同一轮同时查询旧的 event_log 召回和新的
Memory Event 账本，比较 event/turn 覆盖、映射、未映射、拒绝来源和超时等指标。

- 默认关闭，可按 UID/character 灰度；
- 不把新事件正文注入 prompt；
- 不写 episodic、identity、storyline 等派生记忆；
- 不改变正式召回排序；
- 只写脱敏 recall trace 和只读观测计数；
- 必须保持有界延迟、SQLite 短超时和有限 worker/slot。

### 2.2 Relation proposer

relation proposer 是后台候选关系发现器：在已通过 scope、schema 和 source policy
检查的事件窗口中调用 LLM，只提出 `same_topic`、`follows_up`、`possible_cause`、
`contradicts`、`supports` 等候选边。

- 候选写入 `event_edge_proposals`，不直接写确定性 `event_edges`；
- 不修改事实、摘要、prompt 或角色发言；
- 不允许跨角色、跨 realm 或跨 isolated source 建边；
- 默认关闭；
- 受独立模型路由、调用次数、token 和 scope 超时限制；
- 观测只返回运行计数、预算、过滤、失败和超时，不返回正文或 prompt。

## 3. 当前审计结论

### 3.1 已存在且保留

- `event_edge_proposer` 已进入 `/settings/feature-flags`，并有独立的
  `event_edge_proposer` LLM routing category。
- `event_shadow_recall` 已有 `/settings/event-shadow-recall`，支持全局开关、
  UID allowlist、Character ID allowlist 和热重载。
- 后端已有只读观测：
  - `/observability/memory-event-shadow-recall`
  - `/observability/memory-event-edge-proposals`
  - 以及 ledger、确定性 edges、migration 的相关观测。
- 角色工具、shadow、proposer、admin forensic 仍必须保持 Reality scope 和
  source isolation 边界；桌面/手机不消费这些后端观测。

### 3.2 当前缺口

- 管理面运行配置页可以开关 proposer，也可以配置 shadow 灰度，但没有把两者的
  实际运行状态、最近调用、过滤、超时、失败和覆盖指标呈现出来。
- 事件证据页能查询事件、前后窗口、关联、审计和迁移状态，但没有 shadow/proposer
  的专门只读观测卡片或按 UID/character 查询入口。
- `event_edge_proposer` 的 generic feature flag 与 LLM routing category 分散在不同
  位置，页面需要明确显示“功能是否启用”和“模型路由是否有效”是两个不同状态。

## 4. 必须修正的代码问题

### 4.1 migration dry-run JSON 合同

- `scan_legacy()` 返回给 CLI 的 `conflicted_event_ids` 必须变成稳定、可序列化、
  排序后的 list，或在 CLI 输出层显式转换；内部 apply 仍可使用 set。
- dry-run 无论空计划、存在冲突、存在 locked/schema mismatch，都必须能输出合法 JSON。
- dry-run 继续零写入：不得创建 ledger、迁移状态、cursor 或 backup。

### 4.2 event_log 跨日期 source 过滤

- `split_blocks()` 必须把 `# YYYY-MM-DD` 作为日期边界保留在正确 section，不能只把
  `##` 识别为块边界。
- source-isolated 块被过滤时，不得吞掉下一日期标题。
- 过滤后 `event_log.search()` 的 days_ago、decay、时间卡片和 trace 必须仍对应真实日期。
- canonical/legacy union 的同日合并行为不得回退。

### 4.3 storyline 跨日期去重

- event_log 聚合的去重键至少包含物理日期和 block identity；同一日期的 canonical/
  legacy 重复块仍应去重。
- 不得因为不同日期的相同无 `turn_id` 文本而丢失第二次真实发生。
- `material_id`、consumed receipt、cursor v3 和重启幂等性必须保持稳定。

### 4.4 migration aggregate status

- 多条 entry 混合时，任何 indeterminate 状态（locked、busy、schema mismatch、
  read failure）都必须保留在总体报告中。
- `comparison_status=ok` 只能在所有需要比较的 entry 都完成且无不确定项时返回。
- 建议显式返回 `indeterminate: true/false`，不得仅依靠 `would_write=0` 让调用者猜测。
- apply 在不确定项存在时继续保持不推进、不绕过备份、不删除旧证据。

## 5. 控制面与观测面实现要求

### 5.1 设置页

- 保留现有 shadow 专用设置卡：enabled、UID allowlist、character allowlist、
  apply mode 和热重载结果必须可见。
- 在 proposer 功能开关附近明确说明：它只产生候选边，默认关闭，不改变正式记忆；
  模型路由页另显示其 effective preset/category 状态。
- 对两个功能显示 effective state，而不是只显示配置文件中的 desired state：
  `disabled`、`enabled-but-no-scope`、`enabled-and-running`、`blocked-by-schema`
  等状态必须可区分。

### 5.2 只读观测页

在现有 Memory Event 观测入口增加只读卡片或折叠区，调用已有 endpoint，不显示正文、
prompt、token 原文、事件内容或敏感路径：

- Shadow：enabled/effective scope、calls、completed、timeouts、busy、cancelled、
  rejected、mapped/unmapped event/turn、coverage 和最近日期；
- Proposer：enabled/effective route、discovered scopes、calls、tokens、budget、
  filtered input、proposed、inserted、duplicate、failed、timeout、schema/source
  rejection 和最近日期；
- 明确标注“候选边未被采纳，不等于确定关系”；
- 观测 API 继续使用 `state.read`，所有 UID/character 输入必须显式 scope；
- 无运行记录时显示“未运行”，不得显示“健康”或推断为“没有问题”。

### 5.3 三面闭环

- 后端设置 API、effective state、观测 API、鉴权 scope 和审计记录保持一致；
- 桌面/手机不新增开关，也不消费 shadow/proposer 观测；
- 更新 `docs/feature-control-surface.md`、`docs/three-repo-interface-catalog.md`
  和 `docs/known-issues.md`，明确 backend-only、默认关闭和观测范围；
- 若编辑 `admin/static/pages/` 或其 JS，按仓库规则同步 fragment/cache version。

## 6. 最小回归测试

使用 `docs/dev-environment.md` 规定的并行入口，不跑串行全量：

- migration CLI：空计划、plan conflict、ledger conflict、locked/schema mismatch 的
  dry-run JSON 可序列化和零写入；
- event_log source：跨日期标题、隔离块位于日期末尾、canonical/legacy 同日 union；
- storyline：不同日期相同无 turn_id 文本保留两次，同日双来源仍只保留一次；
- settings：feature flag 与 shadow 灰度 API 的 desired/effective 状态、allowlist、
  reload status 和鉴权；
- observability：shadow/proposer endpoint 的脱敏、scope、空运行状态和计数；
- 原有 Memory Event read tools、pipeline read scope、source isolation、storyline、
  proposer、shadow focused tests 回归。

## 7. 验收标准

- [x] MER-10 复核的四个确定性问题全部有代码修正和回归测试。
- [ ] migration dry-run 在真实服务器样本上只读运行并输出合法 JSON（部署后执行）。
- [x] shadow/proposer 的 desired、effective、运行和失败状态在管理面可区分。
- [x] 两类观测不泄露正文、prompt、token 原文、事件证据或本机路径。
- [x] shadow/proposer 仍默认关闭，不进入正式 prompt，不写派生记忆。
- [x] 事件工具、admin forensic、Dream/Stage、source isolation 和原有聊天路径不回退。
- [x] 相关测试使用 `pytest -n auto` 通过，`git diff --check` 通过。
- [x] 只改代码、测试、文档和管理面资源；不提交 `data/`、`userdata/` 或服务器运行产物。
- [x] 完成后立即创建独立 Git commit，再把本工单状态改为 completed。

## 8. 上线顺序

1. 先部署本工单代码，shadow/proposer 保持关闭。
2. 运行只读 migration dry-run，检查冲突、未知来源、already_live、would_write 和不确定状态。
3. 快照确认后，再由维护者决定是否小批量 apply 历史数据；旧 Markdown 和媒体不得删除。
4. 先按单个 UID/character 开 shadow，观察覆盖率、超时和拒绝来源。
5. proposer 只有在 shadow 数据和 schema/source health 足够稳定后才考虑灰度，候选边仍需
   独立审核或后续明确的采纳策略。
