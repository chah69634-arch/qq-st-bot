# Brief 187：统一 UTC `Z` 时间解析，恢复 Python 3.10 hidden-state 契约

## 背景

Python 3.10 的 `datetime.fromisoformat()` 不接受尾缀 `Z`，但 hidden-state 持久化与测试使用标准 UTC `Z` 时间。`core/memory/user_hidden_state.py` 当前在 `apply_time_decay()` 和 `read_afterglow_residue()` 直接解析，异常分别退化为零衰减和丢弃 residue，造成 6 个 full-pytest 失败；Python 3.12 不暴露该问题。

## 施工范围

- 增加一个最小、纯函数的 ISO-8601 UTC parser，兼容 `Z` 与显式 offset；不要散落字符串替换。
- `apply_time_decay()` 与 `read_afterglow_residue()` 共用该 parser。
- 保持无效时间戳现有 fail-closed 行为及日志语义，不改变衰减公式、TTL 或落盘格式。
- 检索同模块相邻时间解析点，仅在同一契约内复用；不要借机全仓重构时间工具。

## 测试

- 指定运行 `tests/test_user_hidden_state_phase5.py` 与 `tests/test_user_hidden_state_decay_consolidation.py`。
- 参数化覆盖 `Z`、`+00:00`、无效字符串和时钟回拨。
- CI Python 3.10/3.12 结果必须一致。

## 验收

- 当前 afterglow 1 个失败与 decay 5 个失败消失。
- Python 3.10 能正确计算 elapsed/age；无效数据仍不抛出到调用方。
- 不通过修改测试时间格式、提高 TTL 或跳过 3.10 测试规避问题。

