# 143 测试数据根隔离与生产残留审计

## 目标

阻止测试用户写入生产 `runtime/memory`，并把已有测试残留与真实用户数据分开处理。

## 已确认

生产树中存在明显测试 UID 目录，例如 `uid_order_test`、`uid_lock_scope_test`、`uid_timeout_test`；它们由 `tests/test_post_process_ordering.py` 使用。目录内主要是可重建的 `vector_store.db`。当前 pytest fixture 已有默认 sandbox 守卫，因此这些更像历史运行残留或绕过 fixture 的旧产物。

## 实施范围

1. 给所有 runtime writer 增加测试模式断言：`mode=production` 下拒绝明显测试 UID/测试 session 写入，或至少写入一次高信号审计并 fail-closed。
2. 检查并修复绕过 `core.sandbox.get_paths()`、缓存旧路径或在导入时读取生产 DataPaths 的测试/模块。
3. 将手动 `run_test.py` 的数据根固定为明确测试区；自动化 pytest 继续使用每 worker 独立临时目录，避免并行互相污染。
4. 管理面和前端显示当前 data mode、测试 session 和测试用户标识，避免测试数据看起来像生产用户。
5. 对现有生产树做只读分类清单：确认真实用户后，再把测试 UID 目录移入统一测试归档或删除可重建索引；本工单不默认删除未知用户目录。
6. 补充“生产模式测试 UID 写入失败”“pytest 不触碰生产路径”“测试模式前端标识”回归测试。

## 验收

- `pytest -n auto`、`run_test.py` 和手动测试入口都不会在生产 memory 根创建测试 UID。
- 现有测试残留有可审计的分类结果，未知目录不被误删。
- 生产用户枚举不会把测试用户展示给前端。

## 备注

本工单只处理边界和残留审计；不要通过清空整个 `data/runtime/memory` 来“解决”问题。
