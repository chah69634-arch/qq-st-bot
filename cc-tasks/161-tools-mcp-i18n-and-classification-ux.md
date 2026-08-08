# Brief 161：工具与 MCP 完整双语、Headers 默认值及分类交互说明

## 背景

“工具与连接 → 工具 → 已注册工具”仍直接展示单语工具描述和内部分类名；MCP 页的 `可选分类映射`、`domain1, domain2`、metadata 状态与权限关系难以理解。MCP Headers 新增行还使用无语义的 `key/value` 空白输入。

后端已经支持 `metadata_mapping`、单工具 `metadata_overrides`、`domain_selector` 和本地 `tool_policy`。本 Brief 只把真实能力准确呈现为可理解的双语控制面，不发明新的 MCP 授权或分类协议。

## 目标

- 所有内置注册工具在管理面都有完整中文和英文描述。
- MCP 页所有自有 UI 文案完整双语；远端服务器原始描述明确标注来源，不伪造翻译。
- 用人话解释“分类映射、领域筛选、远端分类、本地分类、授权、会话暴露”的区别。
- Headers 默认提供安全、可编辑的 Authorization 环境变量模板。
- 保持本地 policy 是执行授权唯一真值。

## 范围

### A. 内置工具描述双语化

- 为 `_TOOL_REGISTRY` 中所有非动态 MCP 工具建立稳定的中文/英文 UI 描述映射，key 使用工具名。
- 至少补齐：
  - `desktop_minimize` 的英文描述；
  - `clear_midterm` 的中文描述。
- `clear_midterm` 中文必须明确：仅在用户明确要求清除近期记忆时调用，只清理短期 mid-term bucket，不影响 episodic memory 或稳定用户档案。
- UI 本地化不能按当前界面语言改写模型实际收到的 canonical tool schema；执行契约与展示文案必须分离。
- 工具分类显示为“可读名称 + 技术 ID”，例如“桌面操作 `desktop`”。
- 增加枚举/静态测试：任一内置工具缺少中文或英文 UI 描述时失败。

### B. 动态 MCP 描述边界

- MCP server 返回的工具名称、描述、metadata 和结果属于远端不可信内容，不纳入静态翻译字典。
- 界面标注“服务器提供的原始描述 / Original description from server”。
- 不把远端英文描述误标为系统英文 UI，也不通过字符串扫描自动翻译 authored/runtime 内容。

### C. 分类能力说明

- 将“可选分类映射”改为默认折叠的高级区，例如“高级：读取服务器工具分类”。
- 在展开前提供双语说明：
  - 部分服务器会在工具 metadata 中声明领域；
  - mapping 告诉 PresenceKit 从哪些字段读取；
  - 普通 MCP 或未声明 schema 的服务器无需填写；
  - 远端分类不授予权限。
- 为内部字段提供可读 label、tooltip 和示例：
  - `namespace`
  - `schema_versions`
  - `schema_version_field`
  - `domains_field`
  - `interaction_field`
- 单工具状态分开展示：
  - 已发现；
  - 已授权；
  - 当前会话已暴露；
  - 服务器声明分类；
  - 本地最终分类；
  - 分类解析状态。
- `metadata_overrides` 的 `remote / override / ignore` 用完整中英文说明，不只显示内部枚举。

### D. domain selector 交互

- 移除 `domain1, domain2` 这种开发占位符。
- 优先汇总当前 server 已发现工具的远端/最终 domains，提供多选标签或 chips。
- 允许输入服务器文档声明但当前尚未发现的 domain；使用英文逗号解析时给出可见标签并去重。
- 示例使用真实语义：`calendar`、`health`、`files`、`hardware`。
- 明确说明：domain selector 只会收窄已经授权的工具；留空表示不按领域过滤；它不能放大权限。
- “包含未分类工具”说明其后果，不能只显示一个孤立 checkbox。

### E. Headers 默认行

- 新建/重置 MCP 导入表单时，默认生成：
  - Header name：`Authorization`
  - Header value：`Bearer ${MCP_TOKEN}`
- 明确这是环境变量模板，不是真实 token；不需要鉴权的 server 可删除该行。
- 不将真实 token 写入文档、测试 fixture 或 tracked 配置。
- Header 输入列使用“名称/值”双语 label，不再以 `key` 作为用户可见默认内容。
- 保持 `${ENV_VAR}` 缺失时 fail-closed，管理面只回显 header 名，不回显密钥值。

### F. 全页 i18n 清点

- 清点 `pages/tools.html`、`js/tools.js`、`pages/mcp.html`、`js/mcp.js` 的所有可见静态和动态 UI 文案。
- 新文案使用语义化 i18n key；中文/英文 key 成对存在。
- `Path A`、`Path C`、effect、allowlist、policy 等保留技术标识，同时提供可理解解释。
- authored/runtime 数据使用 `.i18n-raw` 或等价边界，不被翻译观察器改写。

## 不在范围内

- 不新增 MCP transport、资源、prompts 或记忆接入。
- 不修改 Path A/Path C、tool loop、execute origin gate 或确认状态机。
- 不根据远端 `readOnlyHint`、名称或分类推导本地 effect/权限。
- 不自动翻译或改写远端 MCP 工具描述。
- 不保存真实 token，不改变 Header 展开和 fail-closed 安全契约。

## 主要文件

- `admin/static/pages/tools.html`
- `admin/static/js/tools.js`
- `admin/static/pages/mcp.html`
- `admin/static/js/mcp.js`
- `admin/static/i18n.js`
- `admin/static/js/core.js`（键值编辑器如需语义化扩展）
- `admin/routers/settings_tools.py`（核对展示契约；非必要不改）
- `admin/routers/settings_mcp.py`（核对契约；非必要不改）
- `core/tool_dispatcher.py`（只在确需补展示元数据时修改）
- `core/mcp_client.py`（只读核对 metadata 与 headers 契约）
- 相关工具/MCP/admin i18n 测试

## 验收标准

- 已注册内置工具在中文和英文界面均显示对应语言描述；两条指定描述补齐。
- 任一新增内置工具若没有双语 UI 描述，测试失败。
- MCP 分类映射、单工具覆盖、领域筛选、授权和会话暴露不再混成一个状态。
- `domain1, domain2` 不再出现；已发现 domain 可直接选择，留空语义清楚。
- 新导入表单默认显示 `Authorization` / `Bearer ${MCP_TOKEN}`，不包含真实凭据。
- 远端分类不会改变本地 policy；现有 MCP 配置 round-trip 不丢字段。
- 中文/英文实时往返后，动态 server/tool 卡片和新插入行仍使用正确语言。

## 验证

- 运行 MCP、settings tools、admin static、admin i18n focused tests。
- 对修改的 JS 执行 `node --check`。
- 增加 DOM/静态测试覆盖默认 Header 行、domain chips/selector、双语工具描述完整性和远端原文保护。
- 浏览器目检空 server、无 metadata、有 metadata、有 override、有 domain selector 五种状态及窄屏布局。
- 修改静态资源/fragment 后更新缓存版本。
- 执行 `git diff --check`。

## 提交边界

相关测试与差异检查通过后提交一张独立 commit，只包含 Brief 161。
