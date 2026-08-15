# Brief 179: Dream postcard 资格判定与 archive 可读性测试契约

## 背景

`tests/test_dream_postcard.py` 有 4 个失败。测试 patch 了 `_archive_turns()` 返回合法 turns，但
`generate_postcard()` 还会调用 `_archive_has_parse_error()` 读取真实 archive；测试 dream id 不存在时被判为
archive unreadable，因此生成和保存分支均未触发。

生产要求是正确的：明信片只能来自完整、可读、已封存的 solo sandbox dream。需要修的是“资格判断的纯函数
边界与 I/O 证据注入方式”，不能粗暴删除 archive 可读性守卫。

## 施工范围

- 明确 `generate_postcard()` 的 archive snapshot/readability 契约，避免同一资格判断一半来自 patch turns、
  一半再次读取文件系统。
- 优先将 archive 读取结果归一成一个 snapshot/result，再一次性传给
  `evaluate_postcard_eligibility()`；保持纯函数不自行读盘。
- 单元测试使用真实 sandbox archive 或完整 patch readability helper，覆盖：合法生成、损坏 JSONL、短梦、
  interrupted hard exit、complete hard exit、重复 dream id、generation_failed retry。
- 保持 `dream_mode == sandbox`、最小 assistant turns、completion、duplicate、archive readable 全部条件。
- 核对 postcard eligibility/exit lifecycle 只读观测与 Brief 164/176 文档，不记录 transcript 正文。

## 验收

- `tests/test_dream_postcard.py` 全部通过。
- 损坏/不存在 archive 绝不调用 LLM、不写 scheduled entry；合法 archive 恰好调用一次 LLM 并原子保存。
- 失败重试不会制造重复明信片；既有 exit lifecycle 与 one-shot archive 不变量保持。

