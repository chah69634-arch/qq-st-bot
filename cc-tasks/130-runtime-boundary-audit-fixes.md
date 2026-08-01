# Brief 130: runtime boundary audit fixes

来源：2026-08-01 全仓运行时边界审计。

目标：修复平时不触发、启用后才暴露的失效功能、异常传播、配置假成功和并发边界问题。每个子项独立测试、独立提交。

## 子项

- [x] 130-A：隔离 admin / QQ 长期任务故障；admin 端口绑定或 serve 异常不得拖垮其他运行时任务，并补生命周期测试。
- [x] 130-B：统一管理面配置写入边界；提供进程内串行、原子写入，并防止 `config.local.yaml` 覆盖导致接口假成功。
- [x] 130-C：补齐后台记忆、画像和梦境 LLM 调用的显式 `char_id`，保证 per-character model routing 对所有 category 生效。
- [ ] 130-D：修正 QQ feature flag 的控制面契约；不能热启停的开关不得宣称或伪装为热生效。
- [ ] 130-E：补齐 Dream Seed 桌面 TypeScript API 和测试，使已注册的 Tauri 命令真实可达。
- [ ] 130-F：修正 `practice.reviewer_preset` 语义，使配置直接选择 preset，或改成真实的 routing category 契约；不得静默回退 chat。
- [ ] 130-G：修复用户画像 pending override 候选切换时的嵌套 mutation 丢失。
- [ ] 130-H：替换 desktop/device WebSocket 毫秒时间戳 ID，保证并发 action ACK 不碰撞。
- [ ] 130-I：模型/视觉客户端热重载前关闭旧连接池，避免重复设置后的资源泄漏。
- [ ] 130-J：清理本轮发现的失效测试契约，恢复测试门禁的可信度；不把 live backend 写生产数据造成的环境污染误判为产品缺陷。

## 验收

1. 每个子项有针对性回归测试。
2. 修改运行时、通道、配置控制面时同步相关文档。
3. 每个子项测试通过、`git diff --check` 通过后独立提交。
4. 最后运行 `pytest -n auto`；若本机 live backend 会干扰数据隔离测试，先停止或明确隔离后再跑。
5. Desktop 跨仓改动在 Desktop 仓独立提交，并回填 commit。
