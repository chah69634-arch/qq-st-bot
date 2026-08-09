# Brief 167：Dream 剧本 YAML 往返与消融开关 i18n

## 背景与现场结论

Dream 剧本的权威持久化格式是
`userdata/characters/dream/scenarios/{script_id}.yaml`，历史
`data/dream/scenarios/*.yaml` 仅作只读兼容来源。当前管理面结构化表单把 document 作为 JSON
object 提交，后端校验后用 `yaml.safe_dump()` 写盘；这条内部 API 合同本身成立，但管理面只允许
导入/导出 JSON，无法直接往返真实 YAML 文件，界面说明也把 JSON 表述成主要备份格式。

Dream Prompt 消融 API 的 `known_layers[].desc` 是稳定的英文技术描述。管理面直接显示该字段，没有按
layer ID 做本地化，因此中文界面仍出现英文释义。当前复选框的实际语义还是“勾选 = disabled”，但
页面没有逐行显示启用/关闭状态，容易把实验配置反向理解。

本 Brief 只修管理面创作与控制面 UX，不改变 scenario runtime、Prompt 内容、阶段推进或角色卡。

## 产品决定

- YAML 是剧本的权威文件格式；JSON 保留为兼容交换格式，不再被描述成唯一备份格式。
- YAML 解析与 schema 校验只在后端完成；管理面不引入第二套浏览器 YAML parser。
- Dream 消融释义以 layer ID 为语义 key 做 i18n；API 原始英文 `desc` 继续作为未知层 fallback，API
  不根据 locale 返回不同结构。
- 开关必须正向表达“启用/关闭”，不能继续只靠“勾选代表 disabled”的隐含约定。

## 范围 A：YAML / JSON 双格式导入

- 文件选择接受 `.yaml`、`.yml`、`.json`，并显示检测到的格式。
- JSON：浏览器可解析成 document 后走现有结构化提交路径。
- YAML：上传文本原样交给后端现有 YAML 解析/验证路径；不得在前端用正则、缩进猜测或第三方 parser
  重新解释。
- 导入只填充编辑器草稿，必须由用户检查并点击保存后才写盘；导入动作本身不覆盖现有剧本。
- 编辑既有剧本时，导入文件内 `id` 与当前 ID 不一致必须阻止；新建时可从文件读取合法 ID。
- YAML/JSON 顶层非 mapping、重复/缺失 stage ID、缺必填字段、非法 disclosure、非法字符 ID 等继续由
  同一份 `scenario_loader._validate_script()` 权威校验，错误转换为可读中文/英文提示。
- 不允许上传路径参与服务端拼路径；最终写入仍只经 `dream_scenario_write_path()`。

## 范围 B：以 YAML 为主的导出

- 主按钮改为“导出 YAML”，导出当前编辑器 document 经后端 canonical serializer 生成的 UTF-8 YAML。
- 保留次级“导出 JSON”，用于交换、调试和旧工作流兼容。
- 已保存剧本可复用 `GET /dream/scenarios/{id}` 返回的 canonical `yaml`；未保存草稿如需导出 YAML，新增
  一个只校验/序列化、不落盘的后端端点，禁止为了导出先创建临时真实剧本。
- YAML 文件名为 `{script_id}.yaml`，JSON 为 `{script_id}.json`；不暴露本机绝对路径。
- 导出必须保留 Unicode 与多行文本语义。YAML 注释无法经过结构化表单 round-trip，界面需诚实说明
  “载入表单并重新导出会规范化格式且不保留原注释”，不得承诺无损文本编辑。

## 范围 C：Dream 消融层中文释义与正向状态

- 为所有 `core/dream/dream_prompt_ablation.py::KNOWN_LAYERS` 建立 semantic i18n key，例如
  `observe.dream_prompt.layer.D1_identity_core`；中英文 key 必须成对。
- 前端以 `layer` 查本地化释义，未知层才回落 API `desc`；不得把 API 原始描述写入翻译表动态执行。
- 每行明确显示“已启用 / 已关闭 / 不可消融”；控件应正向表达“启用此层”。如果保留 checkbox，保存时
  必须在 UI adapter 中显式反转为 `disabled_layers`，并有单测覆盖。
- `DX_exit_protocol`、`D10_user_message` 继续不可消融；不可通过 UI、请求构造或语言切换绕过。
- `D9_dream_history` 关闭警告完整 i18n；切换语言后列表文字和状态实时刷新，不需要重新加载页面。
- 页面说明补充：消融只过滤最终 Prompt，不阻止 loader/state 计算；它是测试工具，不是永久玩法配置。

## 范围 D：缓存、可访问性与文档

- 修改 `admin/static/pages/` fragment 时更新 `ADMIN_UI_FRAGMENT_VERSION` 与 `index.html` 中 `core.js?v=`。
- 修改直接加载的 JS/CSS 时更新对应 `?v=`。
- file input、格式按钮、开关状态提供 label/aria；键盘可完成导入、保存和导出。
- 同步 `docs/dream.md`、`docs/prompt-layers.md` 中剧本格式与消融 UI 说明。

## 不在范围内

- 不把权威存储改成 JSON，不迁移/重写真实 YAML，不删除 legacy fallback。
- 不实现 YAML 源码编辑器、注释 round-trip、任意文件浏览器或路径输入框。
- 不改变 scenario schema、Prompt、角色卡、阶段推进或 Dream runtime。
- 不修改 Reality `/prompt-ablation` 的层名与行为；可复用展示 helper，但两个状态文件仍隔离。

## 预计主要文件

- `admin/static/pages/dream-settings.html`
- `admin/static/js/dream-settings.js`
- `admin/static/js/observability.js`
- `admin/static/i18n.js`
- `admin/static/js/core.js`
- `admin/static/index.html`
- `admin/routers/dream.py`
- `core/dream/dream_prompt_ablation.py`（仅在 layer 清单测试需要时；不改语义）
- `docs/dream.md`
- `docs/prompt-layers.md`
- focused admin/scenario/i18n tests

## 验收标准

1. 真实 `.yaml` / `.yml` 与 `.json` 均能导入同一结构化表单，经同一 schema 校验后保存为 canonical YAML。
2. 默认导出得到可被 `scenario_loader.load_script()` 读取的 `{id}.yaml`；JSON 次级导出仍可用。
3. 编辑器对注释不保留、legacy copy-on-write、真实写入位置的说明准确。
4. 中文界面不再出现 Dream layer 英文释义；英文界面完整，运行时切换即时更新。
5. 用户能明确看出每层当前是启用、关闭还是不可消融；保存后的 `disabled_layers` 与界面正向状态一致。
6. DX/D10 不可消融不变量、Reality/Dream 消融隔离和既有 scenario CRUD 零回归。

## 验证

- focused `pytest -n auto`：YAML/JSON 导入、canonical serialize、ID mismatch、invalid schema、legacy
  copy-on-write、scope/path 安全、Dream ablation API 与 admin i18n 完整性。
- `node --check` 覆盖修改的管理面 JS；静态测试验证每个 KNOWN layer 都有中英文 key。
- 浏览器目检中文/英文、启用/关闭/不可消融、YAML/JSON 导入导出、错误状态和窄屏；未完成真实浏览器
  目检则状态标记 partial。
- `git diff --check`，并确认没有修改真实 `userdata/`、`data/` 或配置文件。

## 建议提交边界

本 Brief 完成相关测试和差异检查后独立提交一次，不与 Brief 168–170 混合。
