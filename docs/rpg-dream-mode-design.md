# 跑团梦境模式设计决策（提案）

> 状态：设计已确认，尚未实现。本文是后端工单的约束来源；在后端接口、隔离测试和观测端点完成前，客户端不得假定该模式已可用。

## 1. 定位

跑团模式是 Dream 的第四种模式，继承 Scenario 的剧本/场景推进与梦境隔离，但不是普通剧本聊天的双栏皮肤。

- 用户是玩家，直接控制自己的行动和秘密意图。
- AI 角色由既有角色卡、人设、记忆和角色侧可见事件驱动；跑团 runtime 不替角色写人格化台词。
- KP 是纯旁白/裁判层，不是一个有独立人格的 NPC。
- 第一版目标是一个用户 + 一个主要 AI 角色 + 一个 KP；数据模型应预留多个 AI 角色，但每回合最多自动触发一个主要角色。

跑团内容默认属于 Dream realm：不写 Reality short-term、episodic、identity、mood、hidden state、afterglow 或普通 stimulus；只保存本场 session、归档和只读观测数据。

## 2. 三方视角与知识隔离

每个事件都必须经过投影，不能把 KP 全量上下文直接注入角色 prompt：

```text
完整世界事件
  -> public_projection       公共场景/已公开事实
  -> player_projection       用户作为玩家知道的事实
  -> character_projection    AI 角色允许知道的事实
  -> kp_private_projection   仅 KP/runtime 保留的事实
```

“用户知道”“角色知道”“角色怀疑”不是同一个状态。角色知识至少支持 `unknown`、`suspected`、`known`、`misbelieved` 四类语义。

角色 prompt 继续走现有角色卡驱动链路，只接收角色可见投影、角色自己的记忆和当前对话；角色不得读取 KP 私密事实、用户秘密行动原文、原始系统 prompt 或其他普通 Reality 工具结果。

## 3. 双栏与统一回合

桌面 UI 为左右双栏：

- 角色栏：AI 角色对白与角色可见事件。
- KP 栏：用户秘密行动、KP 裁定、骰点卡片、玩家可见秘密结果、共享场景状态。

两栏不是两套独立会话。所有输入进入同一个 `round_id`：

```text
user_action
  -> kp_adjudication
  -> optional_dice_roll
  -> world_events
  -> knowledge_projections
  -> optional_character_generation
  -> round_end
```

用户可以从任一栏继续游戏。角色栏输入默认为角色可见行动；KP 栏输入默认为玩家/KP侧行动或规则询问。秘密行动必须由用户显式选择/进入 KP 栏，不依赖系统猜测自然语言意图。

KP 可以自动推进：裁定后将角色可见事件交给 AI 角色，角色按自己的角色卡作出回应。每回合默认最多一次裁定、一次骰点链、一次主要角色回应和一次环境追加事件，防止隐式无限链。

## 4. 检定与骰点

第一版采用通用叙事检定，不绑定具体规则书：

- KP 选择检定类型、骰式、修正、难度与可见性。
- 后端确定性骰子引擎生成骰面；保存 seed/公式/修正/DC/结果，支持审计与重放。
- 结果至少支持 `critical_failure`、`failure`、`success_with_cost`、`success`、`critical_success`。
- KP/runtime 可以判定 `automatic_success` 或 `automatic_failure`；常识性观察、没有不确定性的动作不强制掷骰。
- LLM 可以提出检定或解释结果，但不能生成骰面、篡改已落盘结果或自行决定权限投影。

## 5. 角色侧最小检定标记

角色不调用普通 Chat 工具，也不输出复杂 JSON。角色只在需要时输出一行短标记，供系统剥离：

```text
<C>我想要观察周围</C>
```

约定：

- `C` 是固定的“请求检定/请求裁定”字母；字母只表示类别，不携带参数。
- 标签正文是一句自然语言需求，推荐使用“我想要……”或“我需要……”开头。
- 标签必须可从普通角色对白中 fail-soft 剥离；剥离后正文仍是合法角色回复。
- 每次角色生成最多接受一个有效 `C` 标记；未知字母、重复标记、嵌套标签或超长正文按普通文本处理并记录观测，不执行工具。
- `C` 只是角色的主观请求，不是事实、不等于必须掷骰，也不决定属性、DC 或结果。

角色请求的处理链：

```text
角色回复 + <C>需求</C>
  -> 剥离标记
  -> KP/runtime 判断 automatic_success / automatic_failure / roll / reject
  -> 更新世界状态与知识投影
  -> 需要时给角色一次补充事件/回应
```

角色收到的是叙事结果，不是原始骰面或隐藏 DC；除非剧本明确规定角色能感知检定本身。角色侧工具只允许这个请求能力，不能暴露 `roll_dice`、`resolve_check`、记忆、网络、硬件或 Reality 工具。

## 6. 工具与数据隔离

跑团工具使用独立命名空间/allowlist（候选名：`dream_rpg`），不混入普通角色工具暴露面。至少分为：

- 角色侧：`request_check` 的标记适配器（只产生提议）。
- KP/runtime 内部：检定裁定、骰点、结果应用、投影发布。

跑团工具的 origin、session、transcript、dice audit、knowledge projection 和观测端点均需独立校验。任何工具结果不得重新包装为 Reality stimulus，不得触发普通 tool loop 或现实记忆写入。

## 7. 纠正、回滚与分支

用户可以在 KP 栏澄清或纠正设定，但不得静默覆盖已确定历史：

- 裁定前的输入可重述并重新处理。
- 已产生骰点/角色回应后，纠正以 append-only 控制事件记录。
- `clarify` 可补充含义；`retcon` / `branch` 必须显式操作并保留目标回合、原因和新分支标识。
- 已落盘骰点不可被普通文本改写。

## 8. 后端优先的实施闸门

实现顺序固定为：

1. 后端 Dream mode/schema、session state、round API、知识投影、骰点审计、角色标记剥离与工具隔离。
2. 后端只读状态/观测端点与最小回归测试；确认 Reality/Dream 隔离和并发/幂等契约。
3. 再做桌面双栏 UI、客户端能力检查、降级提示、版本化静态资源和端到端验证。

客户端不得通过读取 runtime 文件猜测模式能力；只依赖后端 API 与显式 capability/effective state。

## 9. 未冻结项

- 具体短标记字母当前暂定 `C`，后端实现前可统一改名，但不能增加复杂参数。
- 通用骰式的默认规则、剧本级规则模板和多个 AI 角色的激活策略留待后续工单；不改变本文件的知识隔离与裁定边界。
