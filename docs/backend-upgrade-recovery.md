# 后端升级与恢复

> **PresenceKit v1.0.0 是第一个受支持的升级基线。Preview v0.x 安装必须通过 backup 加全新安装完成迁移。**

## 兼容性策略

| 已安装来源 | 升级策略 |
|---|---|
| v0.x preview / 无法识别的安装 | 不支持自动升级。备份私有状态，在新目录安装 v1，然后只复制受保护数据。 |
| 带受支持 layout marker 的 v1.0.0 及更高版本 | 在完成升级前 backup 的前提下，支持连续向前升级。 |
| 数据 layout schema 比当前程序更新 | 在写入前拒绝；使用兼容版本或恢复 backup。 |
| Downgrade | 不支持；恢复 updater 创建的升级前 backup。 |

这并不是历史迁移引擎。C1.1 writer gate、C1.2 分层读取、C1.3 检查和 C1.4 `bundled/` 都是正常 v1 行为；它们不会让 preview 安装具备自动转换资格。

## 从 preview v0.x 迁移到 v1

1. 停止 PresenceKit，并按 [offline-state-backup.md](offline-state-backup.md) 的说明创建/验证独立的私有状态快照。updater 的 rollback copy 不能替代该快照。快照覆盖 `data/`、`userdata/`、`config.yaml`、存在时的 `config.local.yaml` 与 `secrets.local.yaml`，以及已分类的 legacy 私有资产。
2. 在**新的空目录**安装 v1。不要覆盖安装到 v0.x 程序目录。
3. 使用 `python main.py backup-state restore <snapshot> --target <new-empty-directory>` 将已验证快照恢复到新的空目标。恢复过程关闭 outbound call、只读且不会替换正在运行的安装。最终切换仍由 operator 审核，并仅限于声明过的私有文件；不要复制旧程序资产或 `defaults/`、`examples/`、`core/`、`scripts/`、`.venv/` 等环境。
4. 在依赖 legacy authored fallback 前，运行只读 C1.3 检查：

   ```bash
   python scripts/authored_root_migration_dry_run.py --fail-on-diverged --fail-on-invalid
   ```

   `legacy-only`、`diverged`、`invalid`、`incomplete` 或 `unresolved` 结果都需要人工复核。命令不会复制、覆盖或删除 authored 资产。
5. 正常启动 v1。当配置、鉴权、角色加载和 Pipeline 初始化成功后，v1 写入 `data/layout_version.json`。它只记录 `product_baseline: "v1"`、data layout schema 版本和第一次初始化该数据目录的 v1 版本。

## v1+ 升级契约

解包式 updater 只接受版本不低于 `v1.0.0` 的来源、不低于 `v1.0.0` 且不 downgrade 的目标，以及可读且 `product_baseline` 为 `v1`、schema 受当前 updater 支持的 `data/layout_version.json`。对于 preview 来源、未知安装、缺失/无效 marker、更新的 schema 或 downgrade，它会在替换程序前失败。

对于有效来源，updater 会校验下载 ZIP 和 SHA-256，创建一份完整的 `_update_backup_<source-version>/` 快照，只覆盖程序文件（包括发行版拥有的 `bundled/` 树），并保持 `data/`、`userdata/`、`config.yaml`、`config.local.yaml`、`secrets.local.yaml`、`.venv/` 和 `tools/uv.exe` 不变。相同版本的重复升级是幂等的。依赖同步发生在覆盖之后；依赖失败不会宣称已自动 rollback。

## 恢复

先停止 PresenceKit。在 v1 安装根目录显式恢复 updater 创建的快照：

```bash
python scripts/update_release.py --restore-backup _update_backup_<source-version>
```

恢复前先保存必须保留的升级后文件。恢复是唯一受支持的 downgrade/recovery 路径；它会把安装恢复到完整快照，不会推断跨版本数据迁移。
