# Brief 198 · Memory Event 03 · 统一入口双写事件账本

> 波次：A / 第四张，必须串行
> 依赖：MEM-02
> 参考：`core/memory/fixation_pipeline.py`、`core/pipeline.py`、`core/turn_sink.py`、`core/write_envelope.py`
> 现状问题：正常聊天只有 turn-level short_term/event_log 写入；通道、媒体、realm 和逐消息 ID 没有进入统一证据账本。

## 改法

1. 在 `capture_turn()`/`Pipeline.post_process_critical()` 的统一写入边界生成或接收逐消息 `event_id`。
2. 保留现有 `turn_id` 生成和 transport `msg_id` 语义，不改客户端协议。
3. 写入新账本时保存：
   - user 与 assistant 的独立事件；
   - `turn_id`；
   - 当前冻结的 uid/char scope；
   - `channel/source`、realm/kind；
   - 原始用户文本、可见 assistant 文本、memory 清洗文本；
   - media reference/hash，而不是把 OCR 描述当成原始媒体。
4. 新账本写失败：
   - 记录 redacted runtime signal；
   - 不阻塞 send、short_term、event_log、slow_queue；
   - 不伪造“已写入”状态。
5. 增加账本写入成功率、失败数、按角色/realm 分布的只读观测。

## 拍板

- 双写默认开启但不参与 prompt；若存储初始化失败自动退回旧链路。
- `event_log` 继续写，不做替换。
- Dream 不能调用 Reality 的 capture 写入口；Stage/web/coplay 按已有隔离合同标记。

## 测试

- QQ、desktop、mobile、scheduler assistant-only turn 的 event_id/turn_id 对齐。
- 发送前 event store 异常时旧链路仍成功。
- Dream、web/coplay、trigger boundary、媒体消息和多角色隔离回归。
- `pytest -n auto`，通过后做一次本地重启后读取验证。

## 不做什么

- 不改变现有 prompt 内容或召回排序。
- 不让模型写 event_edges。
- 不做历史回填、删除策略或客户端 UI。
