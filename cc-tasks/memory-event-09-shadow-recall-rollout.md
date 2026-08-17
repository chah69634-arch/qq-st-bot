# Brief 204 · Memory Event 09 · shadow recall 与 prompt 灰度

> 波次：C / 第九张，必须串行
> 依赖：MEM-06、MEM-07、MEM-08
> 参考：`core/pipeline.py`、`core/prompt_builder.py`、`core/recall_trace.py`、`core/prompt_ablation.py`
> 现状问题：在没有新旧对比数据前，直接把完整事件链放进 prompt 会增加 token、误关联和体验漂移风险。

## 改法

1. 新旧召回并行运行，默认只发送旧结果。
2. 新路径输出 shadow trace：
   - seed event IDs；
   - expand/related 结果数；
   - token/字符数；
   - 新旧重叠率；
   - scope/realm 拒绝数；
   - 截断和超时原因。
3. 增加配置开关和灰度范围：global default off，按 uid/char 可开。
4. 第一阶段只把 `event_id` 加入 recall trace，不加入模型 prompt。
5. 第二阶段只在明确触发时让角色调用 read tool；自动注入仍关闭。
6. 灰度期间监测：幻觉、错误引用、重复复述、上下文长度、响应延迟和跨域泄漏。
7. 任何错误或指标恶化都能单开关回退旧路径。

## 拍板

- 新事件链不替代 identity、mid-term、episodic、storyline 的常规注入。
- 自动 prompt 注入不在本工单默认开启。
- 没有足够 shadow 数据，不允许以主观“看起来更完整”作为上线依据。

## 测试

- prompt snapshot、层裁剪、token budget、tool loop disabled 和 active character 切换。
- Dream/Stage/source-isolated turn 不会被 shadow 结果越权注入。
- 灰度开关热重载、回退和观测端点。
- `pytest -n auto`，必要时运行 `tests/run_eval.py`。

## 不做什么

- 不删除现有 recall trace。
- 不把 shadow 数据写入 memory consolidation。
- 不在本工单调整模型 preset 或角色人设。
