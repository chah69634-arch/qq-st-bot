# Brief 139：管理端能力入口与 UI 组件边界整理

## 目标

补齐已存在后端能力但管理端缺少入口或状态说明的部分，并为高频 UI 抽出最小的语义化组件边界。只接已有 API，不新增业务能力，不改变权限模型。

## 范围

1. Token 页面能力说明
   - 后端已有：`/auth/whoami`、`/auth/profiles`。
   - 在 `admin/static/pages/auth-tokens.html` 与相关 JS 中增加当前 token 身份、profile 和 scope 的只读查看入口。
   - 不显示 token 明文，不改变创建、轮换、停用、删除流程。

2. 角色资产绑定入口
   - 后端已有：`/character/{char_id}/asset-bindings`、`/character/{char_id}/model-routing`。
   - 复核 `admin/static/pages/character.html` 和 `admin/static/js/character.js`，为角色级 TTS 预设、表情包、Live2D/3D 模型绑定提供清晰入口，或明确标注该能力暂不开放。
   - 若接入，必须展示保存中、保存成功、失败和当前生效来源状态。

3. 设置来源与生效范围
   - 对 Setup、Status、Model Routing、Observe 页面中重复出现的配置增加简短的“配置来源/生效范围”提示。
   - 重点覆盖 TTS 自动播放、模型路由、调度/唤醒、邮件、纪念日、日记路径和 coplay 白名单。
   - 不把只读观测页面伪装成可编辑页面。

4. 最小组件边界
   - 从 `admin/static/style.css` 与页面 fragment 中抽出语义化样式：`admin-toolbar`、`admin-card-header`、`admin-field-grid`、`admin-action-group`、`admin-result-panel`。
   - 仅替换本工单涉及页面的编号式 `admin-inline-*` 类。
   - 不引入新框架。

## 不在范围内

- 不新增后端 endpoint。
- 不修改 token scope、鉴权规则或配置文件 schema。
- 不把所有观测接口都做成编辑页面。
- 不清理与本工单无关的 legacy UI 类。

## 验收标准

- Token 页面可以查看当前身份和 scope，但任何页面都不回显 token 明文。
- 角色页对资产绑定能力要么可完整保存并显示结果，要么明确显示“当前不可用/暂未开放”，不得留下无效按钮。
- 任何新增状态展示都有明确的只读/可编辑标识和失败反馈。
- 静态 API 调用与后端路由路径一致；保存类操作保留现有鉴权和错误处理。
- 对新增落盘或审计状态不做无观测写入；若只消费现有接口，不新增落盘物。
- 更新 `admin/static` JS、CSS 或 fragment 后同步更新缓存版本号。
- 运行相关静态资源测试，并执行 `git diff --check`。

## 主要文件

- `admin/static/pages/auth-tokens.html`
- `admin/static/pages/character.html`
- `admin/static/js/settings.js`
- `admin/static/js/character.js`
- `admin/static/js/setup.js`
- `admin/static/style.css`
- `admin/routers/auth_tokens.py`（只用于核对契约）
- `admin/routers/character.py`（只用于核对契约）

