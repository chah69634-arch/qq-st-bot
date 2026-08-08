# Brief 160：冻结 Garden 论坛唤醒管理面入口

## 背景

Garden 论坛唤醒当前暂不使用，且上游协议已经变化。继续在管理面展示状态、配置模板和测试唤醒，会让用户误以为该集成仍处于可配置、可验收状态。

本 Brief 只冻结前端控制面；保留现有后端兼容链路，等待上游契约稳定后另单恢复。

## 目标

- 普通用户不再从管理面进入或操作 Garden 论坛唤醒。
- 旧 deep link 不执行状态读取、模板生成或测试唤醒，只显示明确的冻结说明。
- 不删除、不改写现有 Wake Bridge、调度、鉴权、队列或运行时接口。
- 不影响 PresenceKit 自身的花园系统、情绪花槽、浇水和 Garden 管理面板。

## 范围

### A. 隐藏入口

- 从主导航、控制中心、外部集成快捷入口和页面上下文入口隐藏 `Garden 论坛唤醒`。
- 保留旧页面 route/deep link 的兼容处理，避免旧书签进入空白页或报 JavaScript 错误。

### B. 冻结页

- 旧 deep link 进入时只显示一张双语冻结卡：
  - 当前集成暂时冻结；
  - 上游协议正在调整；
  - 当前版本不建议配置、测试或据此判断运行状态；
  - 后端兼容代码保留，恢复将由后续工单完成。
- 冻结页不得调用：
  - `GET /integrations/garden/status`
  - `POST /integrations/garden/test-wake`
- 不生成本地命令模板，不引导创建/轮换集成 token，不展示“运行中/缺失”等可能误导的实时状态。

### C. i18n 与缓存

- 冻结说明、导航变化和 deep-link 页面必须完整支持中文/英文实时切换。
- authored/runtime 内容不进入翻译范围。
- 修改 fragment、CSS 或直接加载 JS 后，按 `AGENTS.md` 更新对应 fragment 与静态资源缓存版本。

## 不在范围内

- 不删除 `admin/routers/integrations.py` 或 Garden 路由。
- 不修改 `WakeBridge`、`submit_garden_wake()`、`TriggerProposal.time_sensitive_external_turn`、调度器、DND、Dream Guard、conversation lock、durable inbox、cooldown、TTL、lease 或 crash recovery。
- 不停止或重启任何本机/上游 Garden 进程。
- 不删除已有 token、配置、队列或运行时状态。
- 不冻结 `core/garden/` 的花园业务功能。

## 主要文件

- `admin/static/index.html`
- `admin/static/pages/integrations.html`
- `admin/static/js/integrations.js`
- `admin/static/js/core.js`
- `admin/static/i18n.js`
- 相关 admin static/i18n 测试

## 验收标准

- 主导航和控制中心不再出现 Garden 论坛唤醒入口。
- 旧 deep link 进入冻结页，不发起 Garden status/test 网络请求。
- 冻结页中英文文案完整、可实时往返切换。
- PresenceKit 花园/情绪相关入口与功能不受影响。
- 后端 Garden 路由、Wake Bridge 和运行时文件无改动。
- 浏览器目检导航、旧 deep link、中文、英文和窄屏；无法目检时状态必须标记为 partial。

## 验证

- 运行相关 admin static/i18n focused tests。
- 对修改的 JS 执行 `node --check`。
- 增加测试，守卫冻结页不会绑定或调用 Garden 状态/测试 action。
- 执行 `git diff --check`，确认不夹带 Brief 159 或其他并行改动。

## 提交边界

相关测试与差异检查通过后提交一张独立 commit，只包含 Brief 160 的前端冻结与测试。
