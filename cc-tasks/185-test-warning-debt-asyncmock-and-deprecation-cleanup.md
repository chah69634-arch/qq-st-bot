# Brief 185: 测试 warning 债务清理

## 背景

Python 3.14.4 全量测试产生 526 条 warning，其中约 485 条来自 `tests/test_sec_auth1.py` 的 AsyncMock 未 await；
其余包括 Starlette/httpx 调用弃用、Pydantic class-based config 和 `asyncio.iscoroutinefunction` 弃用。
这些 warning 不计入当前 59 个失败，不应阻塞前述回归修复，但数量已足以掩盖新 warning。

## 施工范围

- 先修 `test_sec_auth1.py` 的 AsyncMock 生命周期和调用方式，禁止用全局 warning filter 隐藏未 await。
- 按依赖当前正式 API 更新 Starlette/httpx 测试调用；若上游尚无兼容 API，使用最窄的、带 issue 说明的过滤。
- 将项目自有 Pydantic model 迁移到当前 config API；第三方 warning 不做 vendored patch。
- 替换项目自有 `asyncio.iscoroutinefunction` 弃用调用，并覆盖 sync/async callable。
- 建立 warning budget：focused suite 零新增，后续全量可按明确 allowlist 逐步降到 0。

## 验收

- 当前 526 条 warning 有分类前后计数；不得以 `filterwarnings=ignore` 整体归零。
- `tests/test_sec_auth1.py` 不再出现 coroutine was never awaited。
- 相关 focused tests 与 `pytest -n auto` 全量通过，记录仍来自第三方的 residual warning。

