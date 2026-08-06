# Brief 138：管理端 UI 响应式与布局一致性修复

## 目标

修复管理端 `admin/static` 中已经确认的移动端溢出、工具栏挤压、卡片头部换行和重复布局规则问题。保持现有深色主题、页面结构和 API 行为不变，优先改善小屏可用性与跨页面一致性。

## 范围

1. 登录卡片
   - 位置：`admin/static/style.css` 的 `.auth-card`。
   - 在 320px 及更窄视口内不产生横向溢出。
   - 保留桌面端约 380px 的视觉宽度，移动端使用视口约束并减少内边距。

2. 卡片头部与操作工具栏
   - 位置：`admin/static/style.css` 的 `.card-header`、`.search-row`，以及 `admin/static/pages/*.html` 中的多按钮操作区。
   - 标题、刷新、保存、删除、清空等操作在窄屏允许合理换行。
   - 用户搜索、Prompt 查询、日志筛选等工具栏不得把输入框压缩到不可用宽度。
   - 优先新增语义化通用类，例如 `admin-toolbar`、`admin-card-actions`，逐步替换编号式布局类；不要一次性重写所有页面。

3. 表单与表格移动端规则
   - 复核 `form-row`、`tbl-wrap` 和所有固定宽度的 `admin-inline-*` 使用点。
   - 保留日志、Prompt 等开发观测表格的横向滚动；用户、Token、关系事实等高频操作表格在小屏至少保证主列和操作列可见。
   - 不允许页面出现 body 级横向滚动。

4. 误触与可点击区域
   - 用户列表不要继续把整行作为唯一关系配置入口；保留明确的展开/关系配置操作。
   - 记忆查看、关系编辑等操作不能因父级点击事件被误触发。

## 不在范围内

- 不迁移到 React。
- 不重做颜色主题、导航信息架构或后端接口。
- 不批量删除所有 `admin-inline-*` 类；只在涉及本工单的页面做语义化替换。

## 验收标准

- 在 320px、375px、768px、1280px 视口下检查登录页、系统状态、用户管理、日志、Prompt 观测、模型路由页面。
- 登录卡片、卡片头部、搜索栏和主要操作区无内容裁切或横向溢出。
- 中文和英文切换后，按钮不因换行变形，标题与按钮仍有清晰层级。
- 用户列表点击 UID/说明文字不会意外展开编辑区；查看记忆按钮行为保持不变。
- 直接加载的 `style.css` 或页面 fragment 发生变化时，按 `AGENTS.md` 规则更新静态资源版本号。
- 运行相关静态资源测试，并执行 `git diff --check`。

## 主要文件

- `admin/static/style.css`
- `admin/static/index.html`
- `admin/static/pages/status.html`
- `admin/static/pages/users.html`
- `admin/static/pages/logs.html`
- `admin/static/pages/observe-prompt.html`
- `admin/static/js/status-users.js`

