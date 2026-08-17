# Brief 197 · Memory Event 02 · 事件证据账本 schema 与存储适配器

> 波次：A / 第三张，必须串行
> 依赖：MEM-01
> 参考：`core/memory/scope.py`、`core/memory/path_resolver.py`、`core/sandbox.py`、`docs/interaction-event-model.md`
> 现状问题：event_log 是可解析 Markdown，字段粒度不足，无法支持逐消息展开、稳定关联键和原始/清洗文本并存。

## 改法

1. 新增 `core/memory/event_store.py`，对外只暴露结构化 API，不让业务直接拼 SQL。
2. 采用 per `(char_id, uid)` 的 SQLite 文件，落在 `MemoryScope` 对应目录并经过 `get_paths()`/resolver。
3. 初始表：
   - `events`：`event_id`、`turn_id`、`seq`、`occurred_at`、`ingested_at`、`uid`、`char_id`、`realm`、`kind`、`actor`、`channel`、`source`、`raw_payload_json`、`raw_text`、`visible_text`、`memory_text`、`media_refs_json`、`redaction_state`；
   - `event_edges`：先建表，暂不自动写模型边；
   - `event_topics`：先建表，暂不进入 prompt。
4. 事件写入必须：
   - append-only；
   - `(uid, char_id, event_id)` 幂等；
   - 有索引：时间、turn、actor、source、realm；
   - 单条写入失败能返回结构化错误，不抛到聊天关键路径。
5. 提供只读 schema/version 观测，便于迁移和损坏排查。

## 拍板

- `event_id` 是逐消息主键；`turn_id` 仍保留为整轮关联键。
- 原始证据与记忆清洗文本分栏保存，任何摘要不得覆盖原始栏。
- 旧 event_log 不在本工单迁移；本工单只交付空账本和适配器。

## 测试

- schema 初始化、升级、幂等追加、并发同 uid 写入、损坏文件 fail-open。
- scope 不能跨 uid/char 读取。
- 使用临时 sandbox；`pytest -n auto`。

## 不做什么

- 不接 `capture_turn`。
- 不提供角色工具。
- 不让 event_store 直接替代 event_log 或 vector_store。
