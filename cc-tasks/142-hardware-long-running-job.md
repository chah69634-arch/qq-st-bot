# 142 硬件长时动作改为异步任务

## 目标

硬件动作（例如持续约 15 分钟）发出后立即结束当前对话轮，角色可以继续聊天，同时系统可靠地管理到期停止。

## 现状

- `core/hardware/buttplug_client.py::vibrate/pattern` 当前在工具调用内 `sleep` 到动作结束，并在 finally 中 stop。
- 网络请求超时、tool-loop 总预算和设备动作持续时间目前耦合。
- `core/tool_ephemeral.py` 的瞬态状态仅供 UI 观察，不能当作设备已开始或已完成的持久状态。

## 实施范围

1. 新增硬件 job 状态：`accepted/started/completed/failed/cancelled/expired`，包含 `job_id`、开始/结束时间和剩余时长。
2. 工具调用只负责校验、登记并启动后台 worker，返回“已受理/已启动”，不返回“已完成”。
3. worker 负责到期 stop、设备断线、异常和显式取消；进程关闭时有明确清理策略。
4. prompt 只读注入当前有效 job 的剩余时间，例如“刚才的动作还剩约 N 分钟”；状态必须由系统计算。
5. 增加只读观测端点和停止/查询接口，沿用现有 scope 与 execute origin 闸门。
6. 补充 fake transport 测试：立即返回、到期 stop、断线、重复启动、取消和重启语义。

## 验收

- 长动作不会占住本轮 LLM/tool loop。
- 设备最终一定收到 stop，或明确进入 `failed/unknown`，不伪造成功。
- 对话中可看到准确的剩余时间，设备断线时提示不会继续倒计时为正常运行。
- `pytest -n auto` 相关硬件/tool/observability 测试通过。

## 风险

不能简单用 `asyncio.create_task(vibrate(...))` 替代；必须先建立 job 状态、取消和退出清理，否则会出现孤儿动作。
