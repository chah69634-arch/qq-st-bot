# 146 主动机会评估与记忆锚定

## 目标

让 autonomy job 真正围绕候选理由和真实记忆做判断，而不是只收到“Autonomy opportunity source: interval”。

## 实施范围

1. 扩展 `core.autonomy.runner` 的内部 prompt 输入，注入结构化 opportunity、系统时间事实、当前用户活跃状态和有限的记忆检索结果。
2. 记忆召回必须由系统按 `memory_query` 执行，并保留来源、时间和 speaker provenance；模型不得把候选 evidence 当作已经发生的对话。
3. 保留最近历史、profile、mid-term 等现有只读上下文，但增加预算和层标识，避免主动机会 prompt 变成普通聊天 prompt 的无界复制。
4. `talk_owner` 的文本必须说明其依据的事实强度；没有可靠锚点时允许只发当下观察或静默，不得编造“想起了”或“记得你说过”。
5. 让 autonomy tool loop 复用已完成的工具事实锚定与硬件 job 状态层；工具完成不等于必须发言。

## 评估维度

- reason-to-message：消息是否回应候选理由；
- memory-grounding：引用的用户事实是否可追溯；
- novelty：是否只是改写早安/午安模板；
- restraint：不适合打扰时是否选择沉默；
- continuity：是否接住未完成主题而非随机换题。

## 验收

- 同一信号在不同真实上下文中可产生不同的行动模式。
- 无记忆、低置信度候选不会生成虚构往事。
- `Run.prompt_snapshot` 能看到 opportunity、召回层和最终 disposition。
- 增加离线 fixture 评估集，覆盖 routine、care、unfinished_topic、memory_reactivation、no-op 五类。
