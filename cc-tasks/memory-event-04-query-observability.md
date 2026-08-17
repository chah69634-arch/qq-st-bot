# Brief 199 · Memory Event 04 · 事件查询 API 与管理面观测

> 波次：B / 第五张，可与 MEM-05 并行
> 依赖：MEM-03
> 参考：`admin/routers/memory.py`、`admin/routers/observe.py`、`admin/scopes.py`、`docs/three-repo-interface-catalog.md`
> 现状问题：管理员只能读按日 Markdown、短期历史和摘要，无法按稳定事件 ID 展开前后文或查看原始关联。

## 改法

1. 增加只读 backend router，例如 `admin/routers/event_memory.py`：
   - `GET /memory-events/{event_id}`；
   - `GET /memory-events/{event_id}/window?before=10&after=10`；
   - `GET /memory-events/{event_id}/related?cursor=&limit=`；
   - `GET /memory-events/search?...` 作为 seed 查询。
2. 所有接口强制 `memory.read`，并校验 uid/char/realm scope。
3. 返回证据字段和 metadata，不调用 LLM，不返回内部 token、完整路径或敏感凭证。
4. 提供分页、最大窗口、时间范围和结果数量上限。
5. 在管理面增加只读入口，或明确记录为 backend/admin-only；同步 OpenAPI、三仓总账和必要的静态资源版本。
6. 查询 trace 记录命中数量、截断原因、scope 和 query 类型，不记录完整敏感原文。

## 拍板

- “前后 10 条”是确定性顺序查询，不经过摘要模型。
- “关联事件”首版只返回已有确定性边；模型候选边等 MEM-08。
- 查询失败只影响观测/工具，不影响聊天。

## 测试

- 鉴权 scope、跨 uid/char/realm 访问拒绝。
- 事件不存在、分页越界、超大窗口、游标失效和损坏数据库。
- 原始文本不会出现在日志、URL 或错误消息中。
- 管理面静态资源 cache 版本和三仓接口文档检查。

## 不做什么

- 不接角色 tool loop。
- 不把新事件结果注入 Reality/Dream prompt。
- 不提供写、修订、删除事件接口。
