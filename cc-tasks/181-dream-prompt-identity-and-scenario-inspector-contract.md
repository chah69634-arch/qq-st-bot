# Brief 181: Dream Prompt 身份锚点、D8 主体性与 Scenario inspector 契约

## 背景

Dream Prompt 有 8 个失败：所有 world 的 D1 缺少“情感底色”身份锚点，non-lucid D1 同样缺失；D8 导演注记
缺少对“你的意志/你发出”的主体性表述；Scenario D4 inspector 的 note 从 `scenario_mode` 变为
`scenario_profile`，测试仍按旧值断言。

前两项是共享 Prompt 不变量回归；D4 则很可能是 Brief 169 的 profile v2 正式契约，需更新测试而非改回旧名。

## 施工范围

- 在共享 D1 identity 模板恢复稳定、世界无关的情感连续性锚点；不得按五个 world 分别复制文案。
- 保持 non-lucid 禁止元认知，新增锚点只能描述身份/情感连续性，不能泄漏“这是梦”或 lucid awareness。
- 调整 D8 director 固定约束，明确导演只描述角色可感知/可执行的行动，用户意志或用户发出的输入不被角色
  代写、替代或宣称。
- 确认 `scenario_profile` 是 Prompt Profile v2 的 canonical inspector note；若是，更新 D4 测试、i18n/观测
  文档；若不是，则集中常量化 note，避免 `scenario_mode/profile` 双写。
- 新增跨 world、lucid/non-lucid、scenario/non-scenario 的最小矩阵，并运行 Dream prompt ablation 相关测试。

## 验收

- `test_dream_world_isolation.py`、`test_dream_threshold_lucid_gating.py`、
  `test_dream_scenario_d4_isolation.py` 通过。
- D1 身份稳定但不注入现实事实；D8 不代写用户；D4 scenario excluded 状态在 messages 与 inspector 一致。
- 更新 `docs/dream.md`/`docs/stage.md` 中 Prompt profile 与 inspector note 真值。

