# Brief 168：Dream 回放复用权威叙事分段渲染

## 背景与根因

实时单人 Dream 的 `/dream/chat` 响应包含后端 `core.narrative_parser` 生成的 `segments` 与
`segmented_content`，桌面 `DreamChatPanel` 因而能分别渲染对白、动作、环境、感受和普通旁白。

历史 archive 只保存已剥离机器控制块的 `role/content/ts`。回放 API 也只返回这三个字段；客户端
`mapArchiveMessages()` 把 assistant `content` 直接映射到 `text`，没有恢复 segments。回放虽然复用
`DreamChatPanel`，实际只走括号/空行的弱兜底，所以与实时 Dream 视觉不一致。

## 产品决定

- 解析真值仍是后端 `core.narrative_parser`；回放不在客户端维护第二套格式规则。
- 历史 archive 保持 write-once，不迁移、不重写；只在专用只读 API 投影时恢复展示 segments。
- 回放继续是纯展示：无动画、TTS、WS、发送、继续梦境或 memory 回流。

## 范围 A：回放 API 的展示投影

- `GET /dream/archive/{dream_id}` 对每条 assistant content 调用与实时 `/dream/chat` 相同的叙事 parser，
  返回可选 `segments` / `segmented_content`。
- user 消息保持原始 content，不做角色叙事解析。
- parser 失败必须 fail-soft：该条仍返回原始 content，并附固定的安全展示 fallback 标记；不能让一条旧
  格式消息使整场回放 500。
- API 不返回 archive 物理路径、sentinel、Prompt、控制块、context snapshot 或其他内部字段。
- 超长回放沿用有界分页/分批展示；不得为解析一次性把无限历史塞进客户端。

## 范围 B：桌面端统一消息映射

- 扩展 `DreamArchiveMessage` 与 normalize 层，严格校验 segment type/text；未知 type 丢弃并回落原文。
- `mapArchiveMessages()` 把 API segments 映射到 `DreamMessage.segments`，把 stripped content 映射到
  `segmentedContent`，最终交给现有 `DreamChatPanel`。
- 抽取或复用一个“后端 canonical Dream message → DreamMessage”的纯 helper，让 live final response、
  group canonical segments 和 replay 不再各自遗漏字段；不得把 WS subscription、TTS 或当前会话写入
  一并抽进 helper。
- 历史消息静态显示，不触发 `parseIncremental()` 的流式乐观闭合、逐字动画或 pseudo-stream。
- 场景、动作、环境、感受、对白在回放中的 class/气泡结构应与实时 Dream final response 一致。

## 范围 C：兼容与安全

- 兼容旧后端不返回 segments、旧 archive 的括号动作、纯文本、多段文本和混合 Markdown 标记。
- 控制块早已在 archive 前剥离；回放 parser 不承担 exit/scenario control 解析，不得让历史文本触发状态机。
- 回放数据不进入 Reality `StateEngine`、Dream 当前 messages、short-term、WS 去重、TTS 队列或 pipeline。
- 只改单人 Dream archive；群聊 Dream Stage 回放另开 Brief。

## 文档同步

- 后端：`docs/dream.md` 的 archive detail 投影与隔离说明。
- 桌面：`docs/backend-integration.md`、`docs/dream-hud.md`（或当前 DreamWindow 权威文档）。
- 明确 archive 原文件仍只存 content，segments 是读取时派生，不是历史迁移。

## 不在范围内

- 不改 archive 文件格式或重写真实历史梦。
- 不重构整个 `DreamChatPanel`、ChatPanel 或 narrative grammar。
- 不新增回放 TTS、动画、继续对话、编辑、删除或导出正文。
- 不修 Brief 170 的退出/Reality handoff。

## 预计主要文件

后端：

- `admin/routers/dream.py`
- `core/narrative_parser.py`（原则上复用，不扩语法）
- `docs/dream.md`
- archive API focused tests

桌面：

- `src/shared/api/dream-types.ts`
- `src/shared/api/dream-replay.ts`
- `src/windows/dream/replaySelection.ts`
- 必要的纯映射 helper
- `src/windows/dream/components/DreamReplayTranscript.tsx`
- focused Vitest 与 Dream 文档

## 验收标准

1. 同一 assistant 内容经实时响应与 archive detail 投影后产生等价 segment 序列。
2. 回放中 say/do/env/feel/narration 使用与实时 Dream 相同的视觉结构；用户气泡不被误解析。
3. 旧 archive 无 segments、非法旧行、部分读取和 parser fallback 均可继续回放。
4. 回放不会触发 WS、TTS、动画、发送或任何 Reality/Dream 状态写入。
5. 长梦分批加载与滚动可用，切换场次时旧请求不能覆盖新选择。

## 验证

- 后端 focused `pytest -n auto`：五类 segment、纯文本 fallback、控制块不复活、partial archive、scope/path
  安全和无 archive 写入。
- 桌面 Vitest：API normalize、mapping 等价、非法 segment fallback、无动画/TTS/WS side effect。
- `npx.cmd tsc --noEmit`、`npm.cmd run build`；若 Rust command 未变则无需 cargo。
- 真实 DreamWindow 目检动作/环境/感受/对白、长记录和中英文空错误态；未目检则 partial。
- 两仓分别 `git diff --check`，不得夹带当前客户端工作区的其他并行改动。

## 建议提交边界

1. 后端 archive read projection 与测试，独立 commit。
2. 桌面 normalize/mapping/render parity 与测试，独立 commit。

两仓依赖按后端先、客户端后施工；整张 Brief 的 E2E 未完成前不得标 complete。
