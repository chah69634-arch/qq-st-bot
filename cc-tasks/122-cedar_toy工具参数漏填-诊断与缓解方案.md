# Brief 122 · cedar_toy 工具参数漏填——诊断与缓解方案

写于 2026-07-25。诊断已定位，方案未实现。承接排查 120 号工单期间发现的
`【cedartoy】command 参数必填` 报错——排查过程顺带查清了根因，本单记录结论并给出
几个候选缓解方向，供拍板后再排期实现。

## 1. 先排除：这不是 120 号尾部花括号机制的锅

`data/runtime/memory/yexuan/1043484516/action_trace.json` 里两次报错
（07-24 23:48:53、07-25 00:23:08）记录的 `origin` 都是 `"assistant_loop"`，不是
120 号新加的 `"assistant_loop_relay"`——两条路径现在已经拆开单独打 origin
（120 号排查时顺手补的可观测性，见 `core/tool_dispatcher.py` 的
`_EXECUTE_ALLOWED_ORIGINS`），这条证据直接实锤：两次失败都走的是模型原生的
结构化 `tool_calls`，跟花括号中转分支无关。

`error.log` 里 07-23（120 号工单当时还不存在）就已经有同一类"必填参数缺失"
报错（`room_id 必填`、`确认重开请在参数中加 confirm=true`），说明这是 cedar_toy
这个 MCP 工具长期存在的问题，不是这次改动引入的新故障。

## 2. 根因：`play` 的 `params` 是彻底 freeform，子游戏自己的参数格式只写在
   `get_guide()` 的自然语言里，schema 层完全没有约束

只读连了一下 cedar_toy 服务器（`session.list_tools()`，不执行任何 play/account
动作、不改游戏状态）查到的真实 `inputSchema`：

```
play(game, action, params)
required: ["game", "action"]
params: { type: "object", additionalProperties: true, description:
  "该 action 需要的业务参数；例如 turtle_soup join 用 {"room_id":"..."}，
   ask 用 {"room_id":"...","content":"..."}；vote 用
   {"announcement_id":"...","options":"1,3,5"}。" }
```

`game`/`action` 是唯一 schema 强制的两项；`params` 的**内部形状对 schema 完全不
可见**，只在 description 里举了 `turtle_soup` 一个游戏的例子，`fishing` 只字未提。
而 `action_trace.json` 里 fishing 自己吐出的文本原话是"已重开新局……调
cmd('he…"（被截断，大概率是 `cmd('help')`）——说明 `fishing` 这个具体游戏要求
`params` 里塞一个只在它自己的 `get_guide(game="fishing")` 说明文字里才提到的
`command` 字段，**这个字段名连 `play` 的顶层 description 都没提**，模型只能靠
"曾经调过一次 get_guide、并在后续轮次里精确记住并复现这个嵌套字段名"来满足它。

这是"一个泛型工具 + 完全自由的 params 对象 + 具体格式只写在另一次工具调用的
自然语言返回里，不进任何 schema"的设计模式——对 LLM 来说是公认的薄弱场景：
读文档和实际调用之间隔的轮次越多、越容易在复现嵌套字段名时掉链子。跟别的
接入方"跑得通"不冲突：可能用的模型上下文精度更高，也可能没深入到需要
`fishing`/`turtle_soup` 这类嵌套 params 的复杂 action，两种因素都可能成立，
不是非此即彼。

## 3. 排除："我们自己的架构分层把 schema/description 搞坏了"这个假设

——基本可以排除，理由（这次一并核实过）：

- `core/tool_dispatcher.py::get_tools_schema()` 直接把 `_TOOL_REGISTRY[name]`
  里的 `description`/`parameters` 原样打包成 OpenAI `{"type":"function",...}`
  格式；mcp 工具这两个字段本来就是 `core/mcp_client.py::_connect_server()`
  连接时从 `tool.description`/`tool.inputSchema` 直接抄过来的，中间没有任何
  裁剪、摘要或格式转换。
- `core/llm_client.py::chat_turn()` 把 `tools` 参数原样传给
  `client.chat.completions.create(tools=tools, ...)`；`apply_prompt_style()`/
  `sanitize_messages()` 只处理 `messages`，不碰 `tools`——`tools` 这条路径上
  没有任何我们自己代码引入的转译层。
- 也就是说，这次核实到的 `play` schema，和模型实际收到的内容逐字一致。

唯一没法排除的是**服务器出口之外的黑盒**：比如某些 OpenAI 兼容网关是否会对超长
`description` 做静默截断——这个我们查不到，因为目前完全没有持久化"实际发给模型
的完整 request payload"这个日志（`core/api_call_log.py::append()` 只记
caller/purpose/provider/model/duration/ok，不含 messages/tools 内容本身）。
如果以后还要排查类似问题，这也是个值得考虑补的观测点（见 §4.3）。

## 4. 候选缓解方向（未拍板，供讨论）

### 4.1（推荐，成本低、收益直接）让模型看到 MCP 服务器自己给出的具体错误文案

现状：`core/tool_dispatcher.py::execute()` 的两个 `except` 分支统一把任何异常
转成 `_TOOL_FALLBACKS.get(tool_name, "工具暂时不可用")` 回填给模型（mcp__ 前缀
工具不在 `_TOOL_FALLBACKS` 字典里，永远落到硬编码的"工具暂时不可用"）。

问题：cedar_toy 服务器其实已经把"缺了什么"说得很清楚——"command 参数必填"
"确认重开请在参数中加 confirm=true"——这些原本是模型完全可以自我纠正、当场
重试的具体反馈，却被本地异常处理吞成了一句毫无信息量的"工具暂时不可用"，
模型看到这句话不可能知道该怎么修正下一次调用。

方向：`RuntimeError(f"MCP 工具返回错误: {text}")`（`core/mcp_client.py::
_format_result()` 抛出）这类"服务器明确告诉你缺了什么"的错误，应该把 `text`
本身（剥掉"MCP 工具返回错误："前缀之类的内部包装）作为 tool 结果回填，而不是
套用本地 `_TOOL_FALLBACKS` 的通用兜底文案；本地网络超时/连接失败等"服务器
没给出具体原因"的异常，才继续用现在的通用兜底。这对钓鱼/海龟汤这类多步游戏
特别有价值：120 号的循环机制现在已经能撑住"再调一次工具"，如果这一次的结果是
"具体缺了 command"，模型大概率能在同一个 loop 里自己带上这个参数重试，不需要
再等一轮新的 nudge 才有效果。

### 4.2 nudge_hint 里加一条"隔轮调用前先复核 get_guide"提示

在 120 号已经扩写过的 tool_loop nudge 里再加一句：像 `play` 这类"参数格式只
在另一次工具调用的返回文本里说明"的调用，如果不确定具体字段名，先重新
`get_guide` 确认一次再调，而不是凭前几轮的记忆直接拼参数。

优先级低于 4.1——4.1 是"出错后立刻给出可操作反馈"，4.2 是"防止出错"，
两者不互斥，但 4.1 落地成本更低、对已经发生的错误也有救援价值。

### 4.3（可选，观测性）debug 模式下记录完整 outbound request

给 `core/llm_client.py::chat_turn()`/`chat()` 加一个仅在 debug 配置开启时生效
的完整 request payload 落盘（含 `tools`），避免下次排查类似问题还要像这次一样
临时写脚本连 MCP 服务器核实 schema。优先级最低，纯粹是"以后查起来更快"，
不影响这次问题本身。

## 5. 这不是我们能直接修的部分

cedar_toy 是别人的服务，`play` 的 schema/参数设计权在对方——4.1/4.2 都是我们
这一侧能独立落地的缓解，不依赖对方改 schema；如果想从根上解决（比如让
`fishing`/`turtle_soup` 各自的参数形状也进 schema、用 `oneOf` 按 `game` 分叉），
需要找 cedar_toy 维护者沟通，不在这次任务范围内。

## 6. 验收要求（实现时补）

- 若采纳 4.1：单测覆盖"mcp 工具返回 RuntimeError（服务器给出具体原因）→ tool
  结果回填服务器原话，不经 `_TOOL_FALLBACKS`"与"非 mcp 或无法解析具体原因的
  异常 → 现状不变，仍走 `_TOOL_FALLBACKS`"两种分支。
- 若采纳 4.2：回归 120 号已有的 `test_nudge_hint_teaches_tail_brace_convention`
  一类用例，确认新增提示不影响原有 `{true}/{false}` 教学内容仍然存在。
- 手动实测一次 fishing/turtle_soup 场景，确认模型在拿到具体错误反馈后能在
  同一个 loop 内自行修正重试。

不紧急，可以和其他工单并行，无前置依赖。
