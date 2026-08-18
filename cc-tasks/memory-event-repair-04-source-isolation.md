# Brief 209 · MER-04 · Memory Event 来源隔离闭环

> 严重度：high / 第四张
> 依赖：MER-02；可与 MER-03、MER-05 分别施工
> 参考：`core/pipeline.py`、`core/memory/event_query.py`、`core/tools/event_tools.py`、`core/memory/event_store.py`

## 现状问题

账本正确记录了 `web`、`dream_echo`、`coplay` source，但 search/window/related 和角色只读工具默认不排除这些来源；`previous/next` 也只按 stream 分组，可把 source-isolated turn 与普通现实轮连接。这样外部内容可能绕过旧 fixation/event_log 的来源隔离，经事件工具重新进入模型上下文。

## 开工前影响审计

1. 列出所有受控 source 值、写入者和当前旧链路过滤规则，以 `docs/memory.md` 来源隔离合同为准。
2. 区分 admin forensic 读取、shadow 评估和角色 tool 读取，三者权限不应机械相同。
3. 检查 deterministic edges、lineage resolver、tombstone 和迁移记录是否需要跨 source 可见性。
4. 核对工具结果的 untrusted framing，不能把“带 source 字段”当作隔离本身。

## 改法

1. 建立集中式 source policy，不在各查询入口散写字符串判断。
2. 管理面 `memory.read` 可按显式参数查看隔离来源，但默认结果和响应必须清楚标记来源。
3. 角色工具默认只读取允许进入现实对话的 source；禁止调用参数自行扩大到 web/dream_echo/coplay。
4. shadow recall 使用与目标召回路径一致的 source policy，否则指标无效。
5. `previous/next` 的 stream identity 纳入 source partition，或明确采用等价边界，禁止普通轮与隔离轮产生可供角色跟随的邻接边。
6. source 拒绝数进入内容无关观测；不记录被拒绝正文。

## 验收

- 同 uid/char/channel 的普通、web、dream_echo、coplay 事件不会被角色工具跨 source 搜索或展开。
- admin 在具备 `memory.read` 且显式选择 source 时仍可做 forensic 查看。
- shadow 与角色目标路径采用同一 source policy。
- source-isolated turn 不进入 mid-term/episodic/identity/storyline，旧过滤回归通过。
- Dream/Stage 仍不能访问 Reality ledger。
- 最小测试：查询 API、三只事件工具、边生成、shadow、旧 fixation source isolation；使用 `pytest -n auto`。

## 不做什么

- 不删除隔离来源的原始账本证据。
- 不把 web/coplay 迁移为普通事实。
- 不扩大客户端或普通 token 的读取权限。

