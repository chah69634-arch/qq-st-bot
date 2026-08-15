# Brief 184: 发布 runbook、location fallback 与独立审计回归清理

## 背景

剩余独立失败包括：

- `main.py` 不再出现 `_profile.get("location") or "杭州"` 的既定 fallback；
- v1 冷启动 runbook 缺少 `## Clean install` 等测试要求 marker；
- 若干静态测试可能只验证历史字面文本，而非当前正式接口。

这些项目应逐项核对当前产品合同，不与 Scheduler、Dream 或工具大工单混修。

## 施工范围

- 恢复 location 的 `or` fallback，并确保进入 probe/weather 的是有效字符串；不得用
  `dict.get(key, default)` 重新引入 None 陷阱。
- 审核 `docs/v1-cold-start-single-user-deployment.md` 对
  `tests/test_v1_cold_start_audit.py` 的全部 marker，一次补齐 clean install、恢复、readiness、鉴权和失败处理，
  不只修第一个失败标题。
- 文档不得写入真实 token、账号、本机绝对路径；命令使用通用占位符。
- 若审计测试断言的是已正式改名的标题/接口，应让测试验证章节语义或 canonical anchor，而非复制旧文案。

## 验收

- `tests/test_profile_location_fallback.py` 与 `tests/test_v1_cold_start_audit.py` 通过。
- runbook 可从干净安装走到 readiness，并包含失败恢复与凭据轮换边界。
- `git diff --check` 通过。

