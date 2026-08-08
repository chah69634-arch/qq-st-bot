# Brief 162：用户数据资产按类别、角色和作用域重组展示

## 背景

后端已经区分通用表情包、角色表情包、参考音频、GPT 模型、SoVITS 模型、Live2D 和 3D 模型包，但当前“用户数据”页将它们压平成一个下拉框、一张表和一个通用的 `Emotion / pack` 输入框。结果是不同逻辑类别看起来像位于同一文件夹，作用域、情绪、pack 和桌面可用性也不清楚。

## 目标

- 按用户理解的资产类型分组，而不是按物理目录平铺。
- 清楚区分通用资产、角色专属资产、pack、emotion、user/legacy 来源和桌面可用性。
- 上传表单只显示当前类别需要的字段。
- 不改变现有 canonical `userdata/` 写入、legacy/bundled 只读回退和删除安全契约。

## 范围

### A. 页面信息架构

将资产分成三个一级区域或 tabs：

1. 表情包
   - 通用表情包；
   - 角色表情包。
2. 语音资源
   - 参考音频；
   - GPT 模型；
   - SoVITS 模型。
3. 角色模型
   - Live2D 模型包；
   - 3D 模型包。

每组显示数量、有效来源、作用域和空状态，不使用一张无分组总表作为主要界面。可保留“全部资产”高级表格用于诊断，但默认折叠。

### B. 表情包展示

- 通用表情包按 emotion 分组。
- 角色表情包先按角色/pack 分组，再按 emotion 分组。
- 每项显示：逻辑 ID、文件名/预览（安全格式时）、emotion、pack、来源、更新时间、大小和当前可用状态。
- 不把通用表情包与角色 pack 混在同一个“通用”列表。
- `user`、`legacy` 使用可读双语标签，并说明 legacy 为只读兼容来源。

### C. 语音资源展示

- 即使参考音频、GPT 模型和 SoVITS 模型共享角色 voice 物理根目录，UI 仍必须按逻辑 category 分开。
- 每项显示角色作用域、逻辑 ID、类型、来源、有效性和绑定影响。
- 不向浏览器返回或展示本机绝对路径。

### D. 动态上传表单

- 选择类别后只显示相关字段：
  - 通用表情包：逻辑 ID、文件、emotion；
  - 角色表情包：角色、pack、emotion、逻辑 ID、文件；
  - 参考音频/GPT/SoVITS：角色、逻辑 ID、文件；
  - Live2D/3D：角色、逻辑 ID、包文件和“桌面支持状态”说明。
- 移除始终出现的通用 `Emotion / pack` 输入框。
- emotion/pack 优先使用已有值选择器，并允许新增安全 ID；校验错误必须说明具体字段。
- 文件 accept、大小提示和支持扩展名来自后端类别契约或同源常量，避免前后端漂移。

### E. 状态与删除

- 明确区分：
  - 已上传；
  - 后端可读取；
  - 当前角色已绑定；
  - 桌面端可实际使用；
  - legacy/bundled 只读。
- Live2D/3D 在桌面消费闭环不存在时继续显示 partial/backend-only，不得标成可用。
- 删除前显示资产类别、角色/pack/emotion、绑定影响和来源；legacy/bundled 不提供删除按钮。
- 保持服务端 impact 检查和二次确认，不依赖前端作为唯一安全门。

### F. i18n 与响应式

- 所有页面文案、类别、状态、空态、错误和确认完整支持中英文。
- authored 文件名、logical ID、pack、emotion 和运行时内容保持原文。
- 窄屏用卡片或可横向安全滚动的表格，不允许操作按钮被挤出视口。

## 不在范围内

- 不迁移、移动、重命名或删除真实 userdata/legacy/bundled 资产。
- 不把物理目录结构暴露为文件管理器。
- 不新增任意路径读取、目录遍历或浏览器文件系统访问。
- 不宣称 Live2D/3D 已被桌面端消费。
- 不修改表情包运行时选择、回退概率或 TTS 合成逻辑。

## 主要文件

- `admin/static/pages/user-data.html`
- `admin/static/js/user-data.js`
- `admin/static/i18n.js`
- `admin/static/style.css`
- `admin/routers/user_data.py`
- `core/userdata_assets.py`
- `core/data_paths.py`（只读核对路径契约；非必要不改）
- `core/asset_registry.py`（只读核对绑定/来源；非必要不改）
- 用户数据/admin static/i18n 相关测试

## 验收标准

- 七个后端 category 在 UI 中按三组清晰呈现，不再像同一文件夹。
- 通用表情包与角色表情包明确分开，并能看见 emotion、pack 和角色作用域。
- 参考音频、GPT 模型、SoVITS 模型分别展示。
- 上传表单随类别变化，只出现有效字段并提交与现有 API 一致的 payload。
- user/legacy/bundled、已上传/已绑定/桌面可用等状态不会混淆。
- 不展示绝对路径，不允许删除只读来源，不污染真实资产。
- 中文、英文、空状态、错误状态和窄屏均完成浏览器目检；未目检则标记 partial。

## 验证

- 使用测试 sandbox/fixture 创建各 category 的合成资产，不触碰生产 `userdata/`。
- 运行 user-data、asset、admin static、admin i18n focused tests（pytest 使用 `-n auto`）。
- 增加 DOM/静态测试覆盖分组、动态字段、scope 展示、只读来源和 partial 状态。
- 对修改的 JS 执行 `node --check`。
- 更新 fragment/静态资源缓存版本并执行 `git diff --check`。

## 提交边界

相关测试与差异检查通过后提交一张独立 commit，只包含 Brief 162。
