# Brief 186：修测试契约和 CI 环境，恢复 fresh-clone full pytest

## 背景

当前 `full-pytest` 在干净 Ubuntu runner 上报告 289 个失败（3.12 证据见 `cc-tasks/临时工单1.md`）。失败主要不是 289 个独立运行时缺陷，而是测试隐式依赖开发者本机的私有角色卡、私有配置和凭据；一个资产解析失败会沿调用链级联。现有 smoke suite 只覆盖精选测试，不能证明全量契约（`.github/workflows/tests.yml`）。

本工单目标是：在无私有 `userdata/`、无真实密钥、无联网要求的干净 clone 中，Python 3.10 与 3.12 使用同一套公开 fixture 和配置通过 full pytest。不得通过跳过失败测试、上传私有资产或给 CI 配真实 token 让红色消失。

## 施工范围

### 1. 公共角色与梦境 fixture（最高优先级）

- 在 `tests/fixtures/` 提供最小可聊天角色卡、角色配套资产和梦境世界；fixture 必须是公开、可审阅、与生产私有角色无关的内容。
- 增加 pytest fixture，在每个测试沙盒内临时安装/注册这些资产，测试结束后清理；不得解禁整个 `userdata/`，不得复制本机私有角色卡进仓库。
- 将依赖 `yexuan`、`hongcha`、`yexuanJ-5412` 等私有角色的测试迁移到 fixture 角色 ID，路径断言使用 fixture ID 或 `DEFAULT_CHAR_ID`。保留真正验证“未知角色/跨角色隔离”的测试语义，不用全局别名掩盖未知资产。
- 对角色名、梦境世界名和路径做参数化，确保同一测试不读取开发者 `config.yaml` 或本机 authored 资产。

验收：fresh clone 中删除/移走 `userdata/` 后，角色加载、Stage、Dream、activity、memory path 相关测试不再因 unknown character asset id 级联失败；fixture 安装范围可由 preflight 列出。

### 2. 配置、owner 与模型客户端隔离

- 测试配置由 fixture 显式构造：明确 `owner_id`、默认角色、Dream/feature flags 和沙盒数据根，不读取开发者私有配置。
- 模型客户端测试使用 fake、不可联网凭据或完全 mock 的 client；构造 client 不得要求 `OPENAI_API_KEY`，也不得发出真实网络请求。
- 对需要功能开关的测试，在测试内显式打开所需开关，并覆盖默认关闭时的行为；不得修改 `config.example.yaml` 迎合私有环境。
- 检查启动/导入路径，避免测试收集阶段就读取真实 token、QQ 号、手机号或本机绝对路径。

验收：清空 `OPENAI_API_KEY` 及项目私有 secrets 后，模型路由、owner chat、Dream 和 feature flag 测试仍可运行；网络调用可通过 mock 断言为零。

### 3. 跨平台角色 ID 校验

- 在 `admin/routers/character.py` 明确按协议拒绝空白、`.`/`..`、`/`、`\\` 和其他路径穿越/分隔符，而不是依赖当前操作系统 `Path` 行为。
- 补 Linux runner 与 Windows 的同一组参数化回归测试，保证 `a/b`、`a\\b` 均返回相同的 4xx 契约。

验收：Ubuntu 与 Windows 测试对非法 ID 得到一致状态码和错误结构；合法 ID 的创建/解析行为不变。

### 4. CI preflight 与 full-pytest 门槛

- 在 `.github/workflows/tests.yml` 的 full-pytest job 增加只输出布尔状态/非敏感名称的 preflight：默认角色可解析、注册角色列表、测试 fixture 根目录存在、凭据是否存在（只输出 `true/false`，不输出值）。
- preflight 失败应在 pytest 前给出可定位错误；禁止打印 token、owner ID、私有路径或资产内容。
- 3.10/3.12 使用完全相同的 fixture、配置生成步骤和 pytest 命令；保留 JUnit artifact。
- 先在本地/CI 分支分别跑 focused fixture/config/id 测试，再跑 `pytest -n auto` 全量；对剩余失败按真实版本兼容问题单独开工单，不把环境级失败混入运行时修复。

验收：两版本 full-pytest 均通过；若暂不能通过，CI artifact 必须能区分 fixture、配置、跨平台和真实代码失败四类，并记录剩余失败数量与首个根因。

## 明确不采用

- 不把 `config.example.yaml` 改成私有角色或真实 owner。
- 不上传/解禁私有 `userdata/`、真实密钥、真实 QQ/手机号。
- 不给 CI 配置真实 token，不以 `skip`、大范围 `xfail` 或全局 warning/filter 隐藏失败。
- 不把所有失败逐个打补丁；先修测试契约和环境边界，再处理剩余真实失败。

## 交付物

- `tests/fixtures/` 公共角色/梦境 fixture 及安装 fixture。
- 配置、模型 mock、owner 隔离的 pytest fixtures 与最小回归测试。
- 角色 ID 跨平台校验实现及测试。
- CI preflight、3.10/3.12 full-pytest 结果和非敏感 JUnit evidence。
- 更新 `docs/known-issues.md`、`docs/three-repo-interface-catalog.md`（如涉及跨端设置/观测）记录未完成项；每个阶段独立 commit。

