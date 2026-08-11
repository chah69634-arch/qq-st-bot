# Brief 172：三仓协议兼容、CI 分层与真实平台验收闭环

## 背景与目标

PresenceKit 后端、桌面端与移动端已有大量单仓单元测试和 focused regression，但目前仍缺少一条可以回答
“这三个固定版本是否兼容、正式产物是否使用正确环境、平台能力是否在真实生命周期下成立”的可复现证据链。

当前主要缺口：

- 三仓没有统一、版本化的 protocol fixtures，也没有绑定三仓 commit 的兼容矩阵；
- Android 原生能力缺少 instrumented tests，通知、无障碍、悬浮窗、Keystore 主要依赖源码契约或人工验收；
- Android 缺少 Doze、进程被杀、设备重启、relay 断线恢复的完整真机矩阵；
- 桌面缺少 Tauri IPC、真实窗口、Live2D/WebGL 与 macOS E2E；
- ChatPanel timer 的卸载、重入和乱序回调竞态没有回归测试；
- 后端 CI 只运行固定 smoke subset，不运行全量 pytest、独立评测或传感器手工冒烟；
- 移动端 release workflow 没有显式使用 `prod` flavor。

本 Brief 的目标不是用一套“万能 E2E”替代各平台测试，而是建立分层证据：协议 contract、PR/夜间 CI、
原生 instrumented test、真实设备/窗口测试和 release gate 各自证明自己能证明的部分。

## 总体原则

1. 三仓以各自 commit SHA 作为兼容矩阵坐标，禁止用未冻结的 floating branch 或“当前最新”充当发布证据。
2. protocol fixture 是版本化的公开合同样本，不是从某次生产流量抄出的 snapshot；不得包含真实 token、用户正文、
   QQ 号、设备标识或本机路径。
3. provider 与 consumer 都必须读取同一 fixture 版本；协议字段新增、删除或语义变化必须显式升级 fixture 并更新矩阵。
4. 单元测试、mock、模拟器、instrumented test、真机测试和人工目检分别记录，不得互相冒充。
5. PR 必须保持可接受反馈时间；全量 pytest 和高成本独立评测按风险拆到 required PR、main/nightly 或 manual gate，
   不把所有昂贵任务无条件塞进每次提交。
6. 真实设备、macOS runner、签名材料或外部服务不可用时，工单只能标记 `partial`，并明确缺失的环境与证据。
7. 每个阶段完成 focused tests、差异检查后在对应仓库独立提交；禁止把三仓修改压成一个含混提交。

## 阶段 A（P0）：版本化 protocol fixtures 与固定 SHA 兼容矩阵

### 合同范围

首版至少覆盖：

- mobile：`POST /mobile/chat` 请求/响应、`client_turn_id`/`turn_id`、mobile queue poll/ack、重复 ack 与错误响应；
- desktop HTTP：`POST /desktop/chat` 请求/响应、`reply_to`、上传引用、错误映射；
- desktop WS：鉴权、assistant stream/final correlation、canonical replacement、action/ack、reconnect 后去重；
- 共享字段：协议版本、时间字段格式、nullable/optional 规则、未知字段兼容、固定错误码；
- 安全反例：客户端不得提交或升级 `uid`、`char_id`、origin、scope、tool capability、文件路径或 token。

Dream、Stage、sensor、device WS 只有在三个仓库中确有 consumer 时才加入同一首版；不得为了“矩阵完整”发明客户端
并不存在的 transport 或 payload。

### fixture 组织

- 在后端建立 canonical fixture bundle 与 manifest，目录名和文件名必须带协议版本，例如
  `tests/protocol_fixtures/v1/`；manifest 至少记录 schema/fixture version、用例 ID、方向、预期结果和变更说明。
- 桌面与移动端不得复制后形成无人校验的独立真相。可在 CI checkout 后从固定后端 SHA 读取 fixtures，或通过带 checksum
  的同步脚本生成受控副本；无论采用哪种方式，都必须有 drift check。
- fixture 使用稳定 JSON/JSONL 等跨语言格式；动态时间、UUID、签名值通过显式 placeholder/normalizer 处理，禁止宽泛地
  删除所有未知字段来让测试“总能过”。
- fixture 更新必须经过 compatibility classification：backward-compatible、consumer-update-required、breaking。

### 固定提交矩阵

- 新增机器可读 matrix，至少记录 backend、desktop、mobile commit SHA、fixture version、执行时间、runner/OS、各 suite 结果、
  证据链接或 artifact ID。
- CI 提供一个显式触发的 cross-repo workflow，按 matrix checkout 三仓指定 SHA；不得默认测试三个仓库各自漂移的默认分支。
- 首版至少验证 `current backend × current desktop × current mobile`；发布前再验证升级方向所需的 `new backend × previous clients`
  或 `previous backend × new clients`，具体窗口写入 release policy。
- SHA 不存在、fixture checksum 不一致、consumer 未实现用例、协议错误码漂移时 hard fail，不能自动改成 skip。
- 固定 SHA 所需的 GitHub 权限、私有仓访问和 artifact retention 必须写入 workflow 文档，不在日志打印 credential。

## 阶段 B（P0）：移动端 release workflow 显式使用 prod flavor

- 审计所有正式 release 入口，包括 GitHub Actions、PowerShell/BAT 包装脚本和发布文档。
- 正式 APK/AAB 构建命令必须显式包含 `--flavor prod`；Dev 构建保持 `--flavor dev`，两个 application ID/label/产物目录不混用。
- release job 在发布前检查 manifest/application ID、version、签名证书与产物文件名；缺少正式签名时 fail loud，不回退 debug
  或临时签名。
- CI 日志和 artifact metadata 输出 flavor 与 application ID，但不得输出 keystore 路径、alias 密码或任何 secret。
- 增加 workflow/static contract test，防止后续删掉 `--flavor prod` 后仍显示绿色。

## 阶段 C（P1）：桌面 ChatPanel timer 竞态测试

至少覆盖：

- component unmount 后 timer callback 不再 set state、发送消息或写入状态；
- conversation/character 切换后旧 timer 不得覆盖新会话；
- 快速连续输入、stream final、retry/reconnect 导致的 timer replacement 只保留最后一个有效实例；
- fake timers 下 advance、cleanup、重复 mount/unmount 可确定复现；
- 乱序 callback、窗口失焦/恢复和 StrictMode 双 effect 不产生重复副作用；
- 测试结束后无 pending timers、未处理 Promise 或跨用例泄漏。

先定位真实 timer owner 和生命周期，不为测试复制一套平行状态机。若竞态根因位于 hook/store，应在真实 chokepoint 修复并从
ChatPanel 行为层回归。

## 阶段 D（P1）：后端 CI 分层

### PR required

- 保留 fresh-clone smoke subset；
- 增加 protocol contract tests；
- 对明确变更范围运行 focused/marker suite；若启用 marker，必须先为现有测试补真实 marker 或删除无效 marker，不能假装
  `audit/contract/smoke` 已有覆盖；
- workflow、测试收集失败、意外 skip 均不得静默成功。

### main / nightly

- 运行 `pytest -n auto` 全量测试，保留 junit、失败摘要和 commit SHA；
- 分别运行不依赖付费/真实外部服务的 identity、format、memeval 等独立评测；
- Coplay 或其他会调用真实 LLM 的评测使用独立 opt-in job，显式标注模型、成本边界和非确定性，不作为普通 PR 的隐形外部调用；
- flaky test 必须登记 owner、原因和到期时间；禁止永久 `continue-on-error` 把红灯变绿。

### 手工与传感器

- `tests/manual/` 传感器脚本不得伪装成自动 pytest；建立 manual workflow/checklist，记录后端 SHA、设备/模拟源、命令、输入、
  输出、时间和证据位置；
- release gate 只在记录真实执行证据后勾选；源码审查或 mocked event 只能记为 contract evidence。

## 阶段 E（P1）：Android instrumented tests

在移动端 `androidTest` 中使用项目当前可支持的 AndroidX Test/Compose/Espresso 体系，首版覆盖：

- 通知 permission、notification channel 创建/幂等、点击 PendingIntent 与前后台行为；
- 无障碍 service 声明、设置跳转、绑定/断开和用户未授权时 fail-closed；不得尝试绕过系统授权 UI；
- 悬浮窗 permission 检查、设置跳转、service/view 创建与移除、进程重建后的状态恢复；
- Keystore key 首次创建、重复读取、加解密、alias 隔离、不可恢复/失效时安全失败；测试不得接触真实生产 token；
- Flutter platform channel 与 Kotlin handler 的方法名、参数、错误码和线程边界。

模拟器 instrumented test 只能证明 Android framework 合同；OEM 后台限制、厂商权限页和真实通知投递仍进入阶段 F。

## 阶段 F（P2）：移动端真实生命周期矩阵

建立版本化测试表，每次执行记录 device model、Android/API level、OEM、battery optimization 状态、app build SHA/flavor、
backend/relay SHA、网络类型、步骤、预期、结果和视频/日志证据位置。

至少覆盖：

- Doze：进入/退出 Doze，延迟窗口内不重复通知，恢复后 durable queue 正确 catch-up；
- 进程被杀：前台、后台、任务划掉和系统回收分别测试，重启后 ack/cursor/未读状态不丢不重；
- 设备重启：boot 后不越权自启敏感能力，用户允许的恢复路径可解释；
- relay 断线：短断、长断、DNS/证书失败、恢复、重复 signal、乱序 poll/ack；relay 仍是 signal-only，不承载聊天正文；
- backend 暂停/升级：移动端退避、恢复、重复请求幂等和 desktop-to-mobile reply mirror；
- 通知、无障碍、悬浮窗在至少一台基准 Android 与一台目标 OEM 真机上的授权/撤销/恢复。

任何只有模拟器或 adb 人工注入的项目必须标成 simulated，不得写成完整真机通过。

## 阶段 G（P2）：桌面真实运行时与 macOS E2E

- Tauri IPC：在真实 Tauri runtime 验证 command 参数、成功/失败映射、窗口销毁、重建和并发调用；Web mock 不算 IPC E2E。
- 真实窗口：主窗口、Chat、Dream/设置等任务涉及窗口的创建、focus、hide/show、close、重启恢复和多显示器/DPI 基础场景。
- Live2D/WebGL：真实模型加载、context lost/restored、窗口隐藏/恢复、GPU/软件回退、资源失败与内存/帧率基线；只有静态资源解析时
  必须保持 `partial`。
- macOS：在真实 macOS runner 或设备验证 build、签名/权限（若适用）、窗口生命周期、Tauri IPC、WebGL 和后端 HTTPS/WSS；
  Windows build 不能替代 macOS E2E。
- 平台证据记录 desktop SHA、OS/架构、Tauri/WebView 版本、GPU、backend SHA、步骤、结果和 artifact。

## 跨阶段观测与报告格式

每种测试输出必须至少能定位：

- 仓库与 commit SHA；
- fixture/protocol version；
- runner、OS、设备或模拟器身份（脱敏）；
- suite 与用例数量、pass/fail/skip；
- 未执行原因和证据 artifact；
- 结论级别：`static`、`unit`、`contract`、`instrumented`、`simulated`、`real-device`、`real-platform`。

发布 readiness 页面只聚合这些事实，不从“某个 CI 绿色”推导“三仓全部通过”。

## 不在范围内

- 不重写现有 desktop/mobile/backend 协议或另造统一 EventBus/EventEnvelope。
- 不把 MCP、资源/Prompt transport 或记忆写入协议塞进客户端 fixture。
- 不为测试绕过 Android 用户授权、系统安全设置、后端鉴权或 scoped token。
- 不在 CI 使用真实用户数据、生产 token、真实日记/对话、正式设备标识或本机绝对路径。
- 不自动发布 GitHub Release、上传商店或安装到未明确授权的设备。
- 不因新增测试顺手修复与失败无关的业务代码；发现 drift/bug 时另开窄范围修复并关联本 Brief。

## 预计主要文件

后端：

- `tests/protocol_fixtures/`（新）
- protocol fixture loader/contract tests（新）
- `.github/workflows/tests.yml`
- cross-repo matrix workflow 与机器可读 matrix（新）
- `pytest.ini`、独立 eval runners（仅分层接线所需）
- `docs/testing-matrix.md`、`docs/v1-release-readiness.md`

桌面：

- fixture consumer/contract tests（按当前测试结构落位）
- ChatPanel 或真实 timer owner 的 focused tests
- Tauri IPC integration harness / platform E2E workflow
- Live2D/WebGL runtime tests 与验收记录模板
- 桌面测试/发布文档

移动：

- `.github/workflows/` release workflow
- `android/app/src/androidTest/`（新或扩展）
- Kotlin notification/accessibility/overlay/Keystore focused harness
- fixture consumer/contract tests
- 真机生命周期矩阵与 release readiness 文档

## 验收标准

1. 三仓存在同一版本 protocol fixture 的 provider/consumer tests，fixture drift 或破坏性变更会使 CI 失败。
2. 一次 cross-repo run 能从机器可读 matrix checkout 三个固定 SHA，并输出可追溯的兼容结果；不存在 floating-head
   “碰巧通过”的发布证据。
3. 移动正式 workflow 显式使用 `prod` flavor，验证正式 application ID、签名和产物；缺少签名时 fail loud。
4. ChatPanel timer 的卸载、会话切换、乱序 callback、reconnect 和重复 effect 竞态有确定性回归测试，测试结束无泄漏。
5. 后端 PR smoke/contract、main/nightly 全量 pytest、独立离线 eval 与手工传感器证据分层清晰；任一结果不冒充其他层。
6. Android instrumented tests 覆盖通知、无障碍、悬浮窗、Keystore 与 platform channel 的核心合同，且不使用生产凭据。
7. Doze、进程杀死、重启、relay 断线恢复在定义的真机矩阵上执行并保留证据；未覆盖设备明确显示 `not-run`，不默认为通过。
8. Tauri IPC、真实窗口、Live2D/WebGL 和 macOS E2E 有真实 runtime 证据；缺少 macOS/真实 GPU 时整体保持 `partial`。
9. 三仓 release readiness 能列出各自 SHA、fixture version、suite 层级、设备/平台和未完成项，不再只写笼统“CI passed”。
10. 三仓 focused tests、各自 `git diff --check` 通过，提交严格按阶段和仓库分离，不夹带当前并行工作。

## 建议施工顺序与提交边界

1. 后端 canonical fixtures、manifest、provider contract tests，后端独立 commit。
2. 桌面 fixture consumer tests，桌面独立 commit。
3. 移动 fixture consumer tests，移动独立 commit。
4. 固定 SHA cross-repo matrix/workflow 与 release 文档，后端协调 commit。
5. 移动 release workflow 显式 prod flavor 与守门测试，移动独立 commit。
6. 桌面 ChatPanel timer 竞态测试及必要最小修复，桌面独立 commit。
7. 后端 CI 分层，后端独立 commit；高成本/真实外部 eval 保持显式 opt-in。
8. Android instrumented tests，按原生能力分一个或多个移动端独立 commit。
9. 移动真机矩阵与执行证据，只在真实执行后更新结果。
10. 桌面 Tauri/窗口/Live2D/WebGL/macOS E2E 与执行证据，只在真实平台执行后更新结果。

前三阶段和 prod flavor 未完成前，不应把发布兼容性标记为 ready；真实设备或 macOS 环境不可用时，不阻塞已经完成的
contract/CI 提交，但 Brief 172 总状态必须保持 `partial`。
