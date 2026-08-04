# Brief 132: 设备动作目标路由与快速 NACK

来源：2026-08-04 `show_heart` 误投桌宠、桌面端返回 `unsupported action type` 的运行日志审计。

## 目标

在不升级桌面协议 v0.1、不引入 hello capability 协商的前提下，为后端 action 建立集中、显式、fail-closed 的目标路由，使设备专属动作不会占用桌宠 WS 或进入桌宠文件队列。

本 Brief 是 v0.1 兼容修复，不是通用 capability 系统。

## 已确认根因

`core.tool_dispatcher._push_desktop_action()` 当前把同一个 action 依次发送给所有在线的 `desktop_ws`、`device_ws`，且桌宠固定在前。`show_heart` 因而必然先被桌宠 NACK，再轮到 ESP32；桌宠未快速响应时还会引入最多 5 秒额外等待。全部 WS 失败后，设备动作还会错误进入桌宠消费的 `agent_actions.json`。

## 实现要求

### 1. 集中 action ownership 路由

在后端建立单一 action 路由表或等价的集中 resolver，至少能返回：

```text
desktop
device
```

当前契约：

- `show_heart` → `device`
- 桌面协议 v0.1 allowlist 内的现有动作 → `desktop`
- 未登记 action → fail-closed，明确返回未注册错误，不得广播给所有 WS

路由逻辑不得散落到 `core/embodiment/heart.py`，该模块只声明动作，不直接 import/call `channels.device_ws`。

### 2. 目标化投递

重构 `_push_desktop_action()` 的命名或内部实现，使其按 resolver 只选择对应 transport：

- device action 不探测、不等待 `desktop_ws`
- desktop action 不发送给 `device_ws`
- 任一动作只等待所属目标的 ack
- 日志必须包含安全的 action type 与 target，不记录参数正文或凭据

可以保留兼容函数名供既有调用方使用，但内部语义必须变成目标化路由，并在文档中说明。

### 3. fallback 边界

- 只有 `desktop` action 可以进入现有桌宠文件队列
- `device` action 在设备离线、NACK 或超时时明确失败，不写 `agent_actions.json`
- 不新增未配套消费者的设备文件队列
- 不把设备离线伪装成“已请求成功”

`core.embodiment.heart.maybe_draw_heart()` 的成功日志必须依据投递结果：只有 ack 成功才写“已执行/已确认”；离线或失败写可诊断但不过度刷屏的日志。

### 4. ESP32 快速 NACK

`firmware/presence-device/src/ws_client.cpp` 收到未知 `action.type` 时必须立即回复：

```json
{"type":"ack","msg_id":"...","ok":false,"error":"unsupported action type"}
```

不得静默不回 ack。错误文本不得包含 token、网络配置或原始 payload。

### 5. 协议冻结边界

禁止：

- 修改 desktop hello shape
- 引入 capabilities 字段或协商流程
- 给桌面 v0.1 新增 `show_heart` action
- 修改现有桌面 action allowlist
- 让桌宠假装成功消费设备动作

未来动态设备能力协商必须另开协议升级 Brief。

## 相关文件

- `core/tool_dispatcher.py`
- `core/embodiment/heart.py`
- `channels/desktop_ws.py`
- `channels/device_ws.py`
- `firmware/presence-device/src/ws_client.cpp`
- `docs/tools.md`
- `docs/channels.md`
- `docs/presence-device-firmware.md`
- `tests/test_device_ws.py`
- 新增或扩展 action routing 单元测试

## 测试

至少覆盖：

1. desktop 与 device 同时在线时，`show_heart` 只调用 device transport
2. `show_heart` 不等待 desktop ack
3. device 离线时不写桌宠文件队列
4. device NACK/timeout 时返回明确失败
5. desktop action 只发送给 desktop transport
6. 未登记 action fail-closed，不发送到任一 transport
7. desktop action 的既有文件 fallback 不回归
8. heart 成功日志只在 device ack 成功后出现
9. 固件未知 action 生成 `ok:false` ack
10. 协议契约测试确认未新增 desktop action/hello 字段

后端使用相关测试路径并行运行；固件运行 `pio run`。若本机缺少 PlatformIO，必须明确记录未完成项，不能声称固件已构建。

## 文档

同步说明：

- action 已按静态 ownership 路由
- `show_heart` 是 device-only
- device action 没有文件 fallback
- 未知 action 双端均 NACK
- v0.1 仍不支持 capability negotiation

## 验收

- 运行日志不再出现桌宠拒绝 `show_heart`
- `show_heart` 不会占用桌宠 ack 等待窗口
- ESP32 离线时不会污染 `agent_actions.json`
- 未知 action 不再被广播或静默超时
- 后端相关测试通过
- 固件构建通过或明确记录环境限制
- `git diff --check` 通过
- 后端与固件同仓一次独立 commit，回填 commit hash
