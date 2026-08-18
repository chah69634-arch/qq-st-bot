# Brief 207 · MER-02 · QQ 媒体事件证据保真

> 严重度：high / 第二张
> 依赖：MER-01
> 参考：`main.py`、`core/media_processor.py`、`core/turn_sink.py`、`core/memory/fixation_pipeline.py`

## 现状问题

QQ 入口在媒体描述拼接前已经保存 `_trusted_user_text`，但调用 `_qq_reality_reply_adapter()` 和 `record_assistant_turn()` 时没有传入。图片 OCR、文件抽取提示因此进入账本 `raw_text`，同时 QQ 路径没有生成 `media_refs`，无法用哈希回到真实媒体证据。

## 开工前影响审计

1. 分别跟踪 QQ 纯文本、图片、文件、图片+文字、解析失败、下载失败的完整调用链。
2. 核对媒体字节何时可用、何时落盘、是否已经计算 SHA-256，避免重复下载和重复大文件读取。
3. 检查 probe 的 trusted text 边界、LLM prompt 的 media context、short_term/event_log 的既有行为，三者不得因修复而混用。
4. 对照 desktop/mobile upload ingest，确认字段语义一致但不把本机绝对路径写入账本或接口。

## 改法

1. `_qq_reality_reply_adapter()` 显式接收并透传 `raw_user_text`、`media_refs`。
2. QQ 图片/文件处理返回受控媒体引用：`kind`、安全文件名、SHA-256；需要时可带受控描述字段，但 OCR/抽取文本不得成为 raw evidence。
3. `raw_text` 只保存媒体拼接前的用户原文；`memory_text` 可继续保存既有 media context，保持旧记忆体验。
4. 无文字媒体消息的 raw text 允许为空，但必须有 media ref；处理失败时写清 redaction/availability 状态，不伪造哈希或描述。
5. 不向查询结果暴露磁盘绝对路径、下载 URL、QQ 文件 token 或临时凭据。

## 验收

- QQ 纯文本的 raw/visible/memory 字段维持现状。
- QQ 图片和文件：raw text 等于用户原始附言，memory text 可包含描述，media refs 含正确 SHA-256。
- OCR 提示、文件抽取提示和系统回应长度指令不出现在 raw text。
- desktop/mobile 现有上传行为不回归；media hash 不重复下载计算。
- 媒体处理失败不阻塞旧聊天和发送。
- 最小测试：QQ adapter 媒体矩阵、dual-write、probe grounding、跨角色 scope；使用 `pytest -n auto`。

## 不做什么

- 不迁移历史媒体文件。
- 不在本工单决定物理删除/保留周期。
- 不改变视觉模型提示词或媒体解析质量。

