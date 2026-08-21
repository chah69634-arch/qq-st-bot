# Brief 219-222：跑团 Dream 后端施工顺序

> 状态：`ready-sequential-batch`

这四张工单存在明确前置依赖，禁止并行改同一套 Dream state/router：

```text
219 Session 基座与生命周期
  -> 220 确定性裁定/知识投影/骰点
    -> 221 KP + 角色卡双视图回合
      -> 222 REST/OpenAPI/回放/观测闭环
        -> 桌面双栏前端工单（本批不写）
```

执行规则：

1. 每张只做本单范围，相关测试与差异检查通过后立即独立 commit。
2. 下一张开工前先读前一张的实际 diff、测试结果和 `/openapi.json`；若实现改变冻结合同，先同步设计文档和后续工单，不得让后续实现自行猜测。
3. 不修改或回滚工作区其他 agent/用户改动。
4. 222 完成前，三仓总账始终把桌面/mobile 消费标为 `open`。
5. 前端工单只依据 222 验证后的 OpenAPI 编写，不依据这些 proposed 示例硬编码。

工单文件：

- `cc-tasks/219-rpg-dream-session-foundation.md`
- `cc-tasks/220-rpg-dream-adjudication-kernel.md`
- `cc-tasks/221-rpg-dream-kp-character-runtime.md`
- `cc-tasks/222-rpg-dream-backend-contract-closure.md`
