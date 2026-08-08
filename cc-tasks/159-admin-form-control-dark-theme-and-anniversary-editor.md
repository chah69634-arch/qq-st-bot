# Brief 159：管理面表单控件暗色统一与纪念日编辑器去重

## 背景

管理面板存在同一组表单控件黑白交错的问题。已确认这不是字段能力、接口或数据语义差异，而是前端样式选择器覆盖不完整：

- `admin/static/style.css` 当前主要覆盖 `input[type=text]`、`input[type=number]`、`textarea` 和 `select`。
- HTML 中省略 `type` 的 `<input>` 在浏览器行为上默认为文本框，但不会命中 CSS 属性选择器 `input[type=text]`，因此回落为浏览器默认白底。
- `type="time"` 等其他原生输入类型也未进入统一暗色样式。
- 自定义纪念日编辑器在 `admin/static/js/setup.js` 与 `admin/static/js/character.js` 中存在近乎重复的渲染、读取、校验和增删逻辑。

## 目标

1. 让管理面所有普通表单输入控件稳定使用现有暗色视觉体系，不再因是否显式声明 `type` 而出现白框。
2. 建立最小、明确、可复用的表单控件样式边界，避免以后新增输入框再次回落到浏览器默认样式。
3. 合并 Setup 与角色页的纪念日行编辑逻辑，保证字段、校验、增删行为和后续维护一致。
4. 不改变任何后端 API、配置 schema、字段含义或保存行为。

## 范围

### A. 统一表单控件样式

- 在 `admin/static/style.css` 中定义统一的普通输入控件样式原语。
- 至少覆盖：
  - 未声明 `type` 的文本输入框；
  - `text`、`number`、`time`、`date`、`datetime-local`、`email`、`password`、`search`、`tel`、`url`；
  - `textarea` 与 `select`。
- 明确排除并保留专用样式：
  - `checkbox`、`radio`、`file`、`range`；
  - `button`、`submit`、`reset`、`image`、`hidden`；
  - 已有专用控件或只读展示区域。
- 统一正常、hover（如适用）、focus、disabled、readonly、placeholder 状态；focus 必须保持清晰可见，不能只依赖颜色极弱的变化。
- 不使用大范围 `input { ... }` 覆盖所有 input 类型，避免破坏 checkbox、文件上传和按钮。

### B. 修正输入框语义

- 为管理面动态模板和静态 fragment 中的普通文本输入框补充显式 `type="text"`。
- 审计 `admin/static/pages/*.html` 与 `admin/static/js/*.js` 中省略 `type` 的 `<input>`。
- 不机械修改 checkbox、time、number、file 等已有明确语义的控件。
- 现有 `.input` 类若保留，必须有明确用途；不得出现“加了 `.input` 但没有对应基础样式”的伪组件边界。

### C. 纪念日编辑器共享边界

- 将以下重复能力抽为共享 helper，并由 Setup 与角色页共同使用：
  - 行 HTML 生成；
  - 值读取与标准化；
  - 必填字段校验；
  - 新增与移除行。
- 字段保持不变：`key`、`month`、`day`、`year_start`、`prompt_zero`、`prompt_years`。
- 保持现有保存端点、请求 payload、空值省略规则和错误提示语义。
- helper 必须继续对写入 HTML 的值调用 `escapeHtml()`，不得引入动态 HTML 注入回归。
- 允许两个页面保留各自的容器 ID、按钮 action、加载与保存函数；只共享真正重复的编辑器逻辑，不建立新的前端框架或通用表单 DSL。

### D. 响应式与可访问性

- 宽屏保持现有字段网格意图；窄屏下输入框、按钮不得溢出卡片或互相遮挡。
- 不能只用 placeholder 代替可访问名称；若本工单触及的动态纪念日行当前没有 label/`aria-label`，应补充稳定的可访问名称。
- number/time 控件在 Chromium 下仍应可操作；不得通过样式隐藏必要的原生交互而无替代方案。

## 不在范围内

- 不修改后端路由、配置模型、纪念日业务逻辑或 scheduler 行为。
- 不重新设计整个管理面信息架构。
- 不引入 React、Vue、Web Components 或第三方 UI 库。
- 不趁机清理所有 `admin-inline-*` 类。
- 不改变 checkbox、文件上传、滑块、按钮和只读观测面板的既有视觉语义。
- 不修改用户数据或生产配置。

## 主要文件

- `admin/static/style.css`
- `admin/static/js/core.js`
- `admin/static/js/setup.js`
- `admin/static/js/character.js`
- `admin/static/pages/setup.html`
- `admin/static/pages/character.html`
- 其他审计命中的 `admin/static/pages/*.html` / `admin/static/js/*.js`
- `admin/static/index.html`（缓存版本）
- `tests/admin_static_assets.py` 及相关 admin static 测试

## 验收标准

- 截图所示纪念日行中的 `key`、数字字段、两个 prompt 字段全部呈现一致的暗色输入框视觉；字段类型差异只影响输入行为，不再影响主题颜色。
- 管理面不存在因省略 `type`、使用 `type="time"` 或其他已纳入范围的普通输入类型而出现的浏览器默认白底控件。
- checkbox、radio、file、range 和按钮没有被普通文本框样式污染。
- Setup 与角色页的纪念日编辑器使用同一套共享渲染/读取/校验逻辑，保存 payload 与改动前一致。
- 动态插值继续经过 `escapeHtml()`；相关静态测试覆盖共享 helper 的两个消费方。
- 桌面宽屏与窄屏均无横向溢出；键盘 focus 清晰可见，disabled/readonly 状态可区分。
- 不新增后端 endpoint，不修改配置 schema，不触碰生产数据。

## 验证

1. 对所有修改的 JS 执行 `node --check`。
2. 运行相关 admin static focused tests；pytest 使用 `-n auto`，临时目录按 `docs/dev-environment.md` 指向仓库内安全路径。
3. 增加或更新静态契约测试，至少守卫：
   - 未声明 `type` 的普通 input 不会回落为白底；
   - 普通输入类型在暗色样式覆盖范围内；
   - checkbox/file/button 等排除项不被污染；
   - 两个纪念日入口消费共享 helper。
4. 在管理面实际目检 Setup 纪念日、角色纪念日，以及至少一个 `time` 输入页面；分别检查正常、focus、disabled/readonly 与窄屏状态。
5. 若无法完成浏览器目检，必须将状态标记为 partial，并明确列出未完成的视觉验收，不能以静态测试代替。
6. 修改直接加载的 CSS/JS 后更新 `admin/static/index.html` 对应 `?v=`；修改 `admin/static/pages/` fragment 后同步更新 `ADMIN_UI_FRAGMENT_VERSION`、`core.js?v=`。
7. 执行 `git diff --check`，确认没有夹带或回滚其他 agent/用户的现有改动。

## 建议提交边界

相关测试与差异检查通过后提交一张独立 commit；该 commit 只包含 Brief 159 所需的管理面静态资源、测试和缓存版本更新。

## 施工前必读

- `AGENTS.md`
- `docs/dev-environment.md`
