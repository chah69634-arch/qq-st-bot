# Brief 103 · PB4 到期收割：删除 Path B

> **已执行 2026-07-30。** 原定 2026-08-10 纯日期观察门槛已取消：本项是功能覆盖与调用链
> 等价性问题，不是数据质量或资金安全任务。删除决定由 7 项动作的注册、payload、权限、
> active-character 作用域和前端协议审计，以及真机冒烟替代。

## 范围

1. 删 `core/pipeline.py::_parse_and_execute_intent` 及调用点。
2. 删 `config.intent_reflex` 配置项（config.example.yaml 同步）、三道守卫、120s 幂等窗口。
3. ~~`toy_invite` 当前沿用 Path B 守卫与幂等窗口（docs/tools.md:451）——迁移到 tool loop / `_push_desktop_action` 正路，不得随删失效。**这是本单最大风险点，先核对 toy_invite 触发链再动手。**~~
   **2026-07-25 已完成**：`toy_invite` 与同样孤儿的 `dream_invite`（原文档未点出，一并核对时发现）均已注册进 `_TOOL_REGISTRY`（`desktop` 类目），Path A/C 均可触发，action payload 与 Path B 一致，前端协议不变。见 `docs/tools.md` 意图解析节、`docs/known-issues.md` PB4 条目。本单最大风险点已解除。
4. 删 `origin="assistant_intent"` 预留分支（docs/tools.md:462）。
5. 删对应测试；docs/tools.md、known-issues 同步更新。

## 验收

- 全仓 grep `intent_reflex`、`_parse_and_execute_intent` 零残留。
- toy_invite 真机验证仍可触发 ToyWindow。
- `pytest -n auto` 通过。
