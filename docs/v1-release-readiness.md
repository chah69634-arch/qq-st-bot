# v1 发布就绪度

> 状态：发布前检查表，不是发布批准。`blocking` 表示在记录证据前不得声称已发布 public v1；它不授权无关的实现工作。

> **PresenceKit v1.0.0 是第一个受支持的升级基线。Preview v0.x 安装必须通过 backup 和全新安装完成迁移。**

## 阻塞项 / 非阻塞项

| 优先级 | 项目 | 当前证据 | 解除证据 |
|---|---|---|---|
| 阻塞 | Android 正式签名 | `android/app/build.gradle.kts` 在 `android/key.properties` 或其 keystore 缺失时，会在 release task 配置阶段失败；debug 签名仅用于开发 | keystore 保管/操作手册、签名 APK 校验，以及从此前签名构建升级的证据 |
| 阻塞 | Android token 安全与迁移 | `BackendSecurityPolicy.kt` 使用 `CredentialMigration` + `AndroidKeystoreCredentialStore`；普通设置与 legacy token key 仅为兼容/迁移保留 | 已安装应用迁移/恢复、替换/删除、写入失败 rollback，以及无明文残留测试 |
| 阻塞 | 后端更新事务与数据恢复 | v1+ updater 创建程序快照并保留受保护根目录；依赖同步仍发生在替换之后 | release candidate 升级/失败/恢复演练和 backup-manifest 证据 |
| 阻塞 | Authored 根迁移恢复证据 | C1.3 为只读检查，C1.1/C1.2 保留 canonical writer/read 分层 | 审核过的 C1.3 结果，以及在依赖 fallback 前人工处理 legacy-only/diverged 资产 |
| 阻塞 | 数据 schema/version 策略 | `data/layout_version.json` 建立 v1 baseline/schema 1；未来 schema 变化需要明确、受支持的 forward path | 每次后续 schema 变化对应的版本矩阵和 forward-migration 证据 |
| 可靠后台声明的阻塞项 | Relay 真机恢复 | queue 有 24 小时 / 500 条上限（`channels/mobile.py`）；relay publisher 会重试/记录日志，但没有 operator alert | 真机矩阵：后台、Doze、进程被杀、重启、relay 丢失/重连；TTL/cap 淘汰和告警证据 |
| 已关闭 | 已退役 intent-reflex 旁路 | capability-equivalence audit 后已移除；桌面工具继续保留既有 gate 和协议 | focused/full pytest，以及 desktop、ToyWindow、DreamWindow 真机 smoke 证据 |
| 阻塞 | 三仓协议 fixture | 当前 desktop v0.1 是跨仓 prose/code；移动端前台聊天使用共享 owner-chat pipeline 的 `/mobile/chat` | v0.1 WS + HTTP correlation + mobile chat/poll/ack 的版本化 fixture，并在三个仓库 head 上执行兼容矩阵 |
| 阻塞 | 安装/升级/downgrade/recovery | v1-only fixture 覆盖 baseline、forward update、重复执行、restore 和拒绝路径 | 三仓 release candidate 演练及记录完备的 operator 恢复证据 |
| 非阻塞 | 未来 WS v1/envelope/EventBus | 尚未实现（`docs/protocol-v0.md`、`docs/interaction-event-model.md`） | 无：明确属于 post-v1 |
| 非阻塞 | Live2D、3D、MCP、hardware、Garden、Activity 扩展 | 不在发布前检查范围 | 仅通过各自 feature work order 处理 |

## v1 更新基线

已退役的 v0.2.2 bridge 不是发布路径。Preview v0.x 不承诺自动升级或数据连续性：用户备份 `data/`、`userdata/` 和本地 configuration/secrets 文件，在新目录安装 v1，然后只复制受保护项目。旧程序树（`characters/`、`content/`、`defaults/`、`examples/`、`core/`、`scripts/`、`.venv/`）不会复制。C1.3 dry-run 标记为 legacy-only、diverged、invalid、incomplete 或 unresolved 的结果需要人工复核。

第一次成功初始化 v1 时，`data/layout_version.json` 记录产品 baseline（`v1`）、data layout schema 和第一次初始化的 v1 版本。它不包含用户内容或凭据，也不是通用 migration framework。v1+ updater 只接受至少为 `v1.0.0` 的 source、相同或更高的 target，以及它支持的 marker schema；preview/unknown source、future schema 和 downgrade 都会在替换程序前失败。

隔离 fixture 矩阵覆盖 fresh marker creation、v1.0.0→v1.0.1 和 v1.0.0→v1.1.0 更新、受保护根目录保留、bundled 替换、幂等性、显式 restore，以及对 pre-v1、unknown、future-schema 和 downgrade source 的拒绝。它只使用 `tmp_path`，不会接触真实数据。

## 必需兼容矩阵

为每个 release candidate 记录精确的 build hash 和 fixture 结果。

| Backend | Desktop | Mobile | 必需断言 |
|---|---|---|---|
| Candidate | Candidate | Candidate | Auth、`/desktop/chat`、`/mobile/chat`、v0.1 WS hello/message/action/ack、mobile poll/ack |
| Candidate | Previous supported | Previous supported | 无 wire/schema regression，或明确拒绝升级 |
| Previous supported | Candidate | Candidate | 明确的不兼容拒绝或受支持行为；绝不能静默损坏 |
| Candidate | N/A | 全新 Android 安装 | Token setup、聊天、poll delivery、没有私有 build-time configuration |

`/mobile/chat` 是当前 Flutter client contract 的一部分，矩阵必须覆盖 mobile request/reply 和 dedupe 断言。

## 发布验证顺序

1. 冻结三个 commit，根据当前 v0.1 contract 生成 protocol fixture；运行 backend、desktop 和 mobile 的 CI/build 检查。
2. 在隔离数据副本上执行全新 v1 安装、同版本重装和 v1 forward update。验证 marker、backup、重启、auth、角色卡分层读取和 mobile queue 恢复。
3. 确认 updater 拒绝 preview v0.x，并且 backup/全新安装迁移流程可用；测试 v1 restore，不测试 downgrade。
4. 在把后台 delivery 描述为可靠之前，完成 Android 签名安装和 relay 真机矩阵。
5. 保留 intent-reflex 旁路的退役证据；不再保留只按日期观察的 gate。
6. 只有在兼容矩阵以及 artifacts/sha256 记录附在发布决策后，才能发布。
