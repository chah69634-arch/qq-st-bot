# Brief 203 · Memory Event 08 · 模型候选关联边

> 波次：C / 第八张，必须串行
> 依赖：MEM-07、MEM-04
> 参考：`core/scheduler/triggers/`、`core/llm_client.py`、`core/model_registry.py`、`docs/model-presets.md`
> 现状问题：用户希望小模型只提出关联边；当前没有候选边 schema、审核状态、预算或模型观测。

## 改法

1. 新增后台 scheduler trigger，例如 `event_edge_proposer.py`，不挂逐轮 slow queue，不发言。
2. 候选关系首版只允许：
   - `same_topic`；
   - `follows_up`；
   - `possible_cause`；
   - `contradicts`；
   - `supports`。
3. 每条候选边保存：输入事件 ID、关系类型、短理由、confidence、model/preset/version、prompt hash、created_at、状态 `proposed`。
4. 输入必须是有限事件窗口或已有 seed，不允许把全库发送给模型。
5. 模型输出严格 JSON，解析失败不写边；单次、每日调用量和 token 上限固定。
6. 增加 `/observability/...` 只读查询：运行次数、候选数、失败数、按关系类型统计。

## 拍板

- 模型候选边不参与 prompt、不影响召回、不改变事实状态。
- `possible_cause` 永远是可能关系，不能渲染成确定因果。
- 不做自动“接受/审核”；后续如需审核另立工单。

## 测试

- JSON 校验、模型失败、超时、重复候选、跨 realm/char 输入拒绝。
- 预算、调度冷却和并发锁。
- 候选边不会进入 `event_log`、short_term、episodic 或 identity。
- `pytest -n auto`，补 runtime signal observability 回归。

## 不做什么

- 不让小模型总结事件。
- 不自动修正或合并原始事件。
- 不在本工单开放角色读取候选边。
