# Authored 根迁移 dry-run

`scripts/authored_root_migration_dry_run.py` 是 C1.3 检查步骤，用于检查安装中是否仍有位于旧位置的私有 authored 资产。它是只读操作：不会复制、移动、删除、覆盖或创建 authored 资产，没有 `--apply` 选项，也不会创建迁移 marker。

在后端仓库根目录运行：

```powershell
python scripts/authored_root_migration_dry_run.py
python scripts/authored_root_migration_dry_run.py --json-output migration.json --markdown-output migration.md
python scripts/authored_root_migration_dry_run.py --fail-on-diverged --fail-on-invalid
```

对于隔离的升级 fixture，`--repo-root`、`--userdata-root` 和 `--legacy-root` 可显式选择安装根目录。报告路径始终使用根别名（`userdata/...`、`legacy/...`、`repo/...`），不会使用普通私有绝对路径。报告只包含 ID、大小、哈希、校验 metadata 和字段完整性，不包含 authored 文本、token、密码、模型内容、音频或视频。

## Resolver 对齐与 manifest

JSON schema 版本为 `presencekit.authored-root-migration-dry-run.v1`。每个资源同时包含候选路径与哈希、等价于生产环境的有效来源、活动引用类型、完整性、状态、建议和原因。文件与 package 的优先级由 `core.authored_asset_resolver` 负责；Dream preset ID 使用 `core.asset_registry` 的稳定映射，包括中文 stem。

扫描范围包括 cards、按角色划分的 authored 文件、模块化及合并后的 Reality lorebook/jailbreak 资产、Dream preset/world package、贴纸、头像、公共 seed/template 根目录、生成的 memeval residue，以及已知配置和 active-asset 引用。大型二进制文件以流式方式计算 SHA-256，不会被解码。

同一逻辑文件或 package 以 `userdata` 为优先。只有 legacy-only 资源才可能在未来迁移计划中成为复制候选；资源发生 divergence 时始终需要人工复核。`bundled/` 是发行版拥有的公共 seed/template 素材，永远不是迁移候选。旧的 `characters/`、`content/`、`defaults/` 和 `examples/` 路径在一个发行周期内仍作为 compatibility-only reader；本 dry-run 永远不会删除私有 legacy 资产。

## Dream package

每个 Dream world 作为一个 package 评估。loader 要求的字段是 `ruleset.md`、`mes_example.md` 和 `vocab.json`；loader 消费的可选字段包括 lorebook、symbolic profile、HUD labels、scene labels 和 meta。报告列出必需/可选字段的缺失情况、选定根目录对 `_default` fallback 的依赖、是否可独立生成，以及同 ID package 的 divergence。

不完整的 userdata package 不会从 legacy package 自动修复。同 ID 冲突的唯一安全建议，是在完成 backup 后由 operator 未来显式选择整个 package。`_default` 和 `reality_derived` 保持各自 loader 语义。

## 未来执行 apply 的前置条件

本 dry-run 产生的是证据，不代表迁移完成。不能仅因为 canonical 目录存在，就删除 legacy 私有资产。未来的 apply 工单必须满足：

1. 已审核的稳定 manifest，并对每一个 diverged、invalid、incomplete 和 unresolved 条目作出明确决定。
2. 已验证的 `userdata` 与 legacy 私有资产子树 backup，并独立保存 manifest。
3. 只有在可逆的 apply 成功后才能写入每次安装的完成 marker；本 dry-run 有意不创建 marker。
4. 完成升级和恢复演练，保护 `userdata/`、legacy 私有 `characters/`、`content/characters/` 和 `assets/stickers/` 根目录，同时保留发行版拥有的 `bundled/` 素材。
5. 有能够恢复 backup 的 rollback 路径，并在 manifest 证据被接受前继续保留 legacy reader。
