"""
Prompt 构建模块
按 SillyTavern 风格的分层顺序组装完整的消息列表
每一层都有清晰的注释说明其来源和作用
"""

import logging
import re

from core.character_loader import Character
from core.error_handler import log_error

logger = logging.getLogger(__name__)

_JAILBREAK_ENTRIES_PATH = __import__("pathlib").Path("data/jailbreak_entries.json")

def _load_jailbreak(layer: int | None = None) -> str:
    """
    读取 data/jailbreak_entries.json，返回启用条目的内容。
    layer指定时只返回该层的条目，None时返回所有启用条目。
    """
    try:
        if not _JAILBREAK_ENTRIES_PATH.exists():
            return ""
        import json
        data = json.loads(_JAILBREAK_ENTRIES_PATH.read_text(encoding="utf-8"))
        entries = data.get("entries", [])
        parts = []
        for e in entries:
            if not e.get("enabled", True):
                continue
            if layer is not None and e.get("layer", 0) != layer:
                continue
            content = e.get("content", "").strip()
            if content:
                parts.append(content)
        return "\n".join(parts)
    except Exception as e:
        from core.error_handler import log_error
        log_error("prompt_builder._load_jailbreak", e)
        return ""

def build(
    character: Character,
    user_id: str,
    user_message: str,
    history: list[dict],
    relation: dict,
    profile: dict,
    group_context: list[dict],
    growth_content: str = "",
    event_search_result: str = "",
    lore_entries: list[str] = None,
    tool_result: str | None = None,
    author_note_extra: str = "",
    affection_info: str = "",
    pet_info: str = "",
    current_time: str = "",
    reminders: list = None,
    diary_context: str = "",
) -> list[dict]:
    """
    组装完整的 prompt 消息列表

    返回 OpenAI 格式的消息列表，直接传给 llm_client.chat()

    参数说明：
        character:           当前角色卡
        user_id:             用户QQ号
        user_message:        本轮用户消息内容
        history:             短期对话历史 [{role, content}, ...]
        relation:            user_relation.get_relation() 的返回值
        profile:             user_profile.load() 的返回值
        group_context:       group_context.get_recent() 的返回值
        growth_content:      character_growth.load() 的返回值（叶瑄对用户的认知）
        event_search_result: event_log.search() 的返回值（相关往事摘要）
        lore_entries:        lore_engine.match() 的返回值
        tool_result:         本轮工具执行结果（有则注入）
        author_note_extra:   consistency_check 发现问题时的纠偏提示
    """
    if lore_entries is None:
        lore_entries = []
    messages: list[dict] = []

    # ─────────────────────────────────────────────────────────────────────────
    # 层 0：破限预设（jailbreak，最高优先级，放在最前面）
    # config.yaml jailbreak.enabled=true 时注入对应预设文本
    # ─────────────────────────────────────────────────────────────────────────
# 层0
    jailbreak_text = _load_jailbreak(layer=0)
    if jailbreak_text:
        messages.append({"role": "system", "content": jailbreak_text})
            

    # ─────────────────────────────────────────────────────────────────────────
    # 层 1：全局 system prompt（来自角色卡的 system_prompt 字段）
    # ─────────────────────────────────────────────────────────────────────────
    if character.system_prompt:
        messages.append({
            "role": "system",
            "content": character.system_prompt,
        })

    # ─────────────────────────────────────────────────────────────────────────
    # 层 2：角色描述 + 性格 + 情境
    # ─────────────────────────────────────────────────────────────────────────
    char_desc_parts = []
    if character.description:
        char_desc_parts.append(f"【角色描述】\n{character.description}")
    if character.personality:
        char_desc_parts.append(f"【性格】\n{character.personality}")
    scenario_text = character.scenario or ""
    if scenario_text:
        char_desc_parts.append(f"【当前情境】\n{scenario_text}")

    if char_desc_parts:
        messages.append({
            "role": "system",
            "content": "\n\n".join(char_desc_parts),
        })

        # 破限条目层2
    jb_layer2 = _load_jailbreak(layer=2)
    if jb_layer2:
        messages.append({"role": "system", "content": jb_layer2})

    # ─────────────────────────────────────────────────────────────────────────
    # 层 2.5：当前时间（让叶瑄知道现在几点、星期几）
    # ─────────────────────────────────────────────────────────────────────────
    if current_time:
        messages.append({
            "role": "system",
            "content": f"【当前时间】{current_time}",
        })

    # ─────────────────────────────────────────────────────────────────────────
    # 层 3：与该用户的关系
    # 来自 UserRelation，说明 bot 该用什么态度对待这个用户
    # ─────────────────────────────────────────────────────────────────────────
    role = relation.get("role", "stranger")
    nickname = relation.get("nickname")
    extra_prompt = relation.get("extra_prompt", "")

    if nickname:
        relation_text = f"该用户是你的{role}，你叫他\"{nickname}\"。"
    else:
        relation_text = f"该用户是你的{role}。"
    if extra_prompt:
        relation_text += extra_prompt

    messages.append({
        "role": "system",
        "content": f"【与该用户的关系】\n{relation_text}",
    })

    # ─────────────────────────────────────────────────────────────────────────
    # 层 4：群聊上下文（仅群聊时注入，私聊时 group_context 为空列表）
    # 格式："群友小明：xxx\n群友小红：xxx\n..."
    # ─────────────────────────────────────────────────────────────────────────
    if group_context:
        ctx_lines = []
        for msg in group_context:
            sender = msg.get("sender_name", "群友")
            content = msg.get("content", "")
            time_str = msg.get("timestamp", "")
            if time_str:
                ctx_lines.append(f"[{time_str}] 群友{sender}：{content}")
            else:
                ctx_lines.append(f"群友{sender}：{content}")

        messages.append({
            "role": "system",
            "content": "【群聊上下文（最近群内动态）】\n" + "\n".join(ctx_lines),
        })

    # ─────────────────────────────────────────────────────────────────────────
    # 层 3.5：生理期感知（在经期时强调注意事项）
    # ─────────────────────────────────────────────────────────────────────────
    try:
        from core.memory.user_profile import get_period_info
        from datetime import date as _date, datetime as _datetime
        _period = get_period_info(user_id)
        _last = _period.get("last_period_date")
        if _last:
            _days = (_date.today() - _datetime.strptime(_last, "%Y-%m-%d").date()).days
            if 0 <= _days <= 7:
                messages.append({
                    "role": "system",
                    "content": (
                        f"【重要】用户现在处于生理期第{_days + 1}天。"
                        f"叶瑄知道这件事，会自然地体现在关心里。"
                        f"不要提议吃冰、喝冷饮、剧烈运动。"
                        f"不需要每句话都提生理期，但态度要比平时更温柔。"
                    ),
                })
    except Exception:
        pass

    # ─────────────────────────────────────────────────────────────────────────
    # 层 3.6：watch数据摘要（最近一次睡眠）
    # ─────────────────────────────────────────────────────────────────────────
    try:
        from core.memory.user_profile import load as _load_up
        _up = _load_up(user_id)
        _segs = [s for s in _up.get("sleep_segments", []) if s.get("duration_minutes", 0) > 0]
        if _segs:
            _last = _segs[-1]
            _dur = int(_last.get("duration_minutes", 0))
            _h, _m = _dur // 60, _dur % 60
            _date = _last["time"][:10]
            _start = _last.get("sleep_start", "")
            _end = _last.get("sleep_end_time", "")
            messages.append({
                "role": "system",
                "content": (
                    f"[身体数据感知] 用户最近一次睡眠：{_date}，"
                    f"入睡{_start}，起床{_end}，共{_h}小时{_m}分钟。"
                    f"叶瑄知道这些数据，可以自然地提及。"
                ),
            })
    except Exception:
        pass

    # ─────────────────────────────────────────────────────────────────────────
    # 层 5：关于这个用户（用户画像，100% 注入）
    # ─────────────────────────────────────────────────────────────────────────
    profile_parts = []
    if profile.get("name"):
        profile_parts.append(f"名字：{profile['name']}")
    if profile.get("location"):
        profile_parts.append(f"地点：{profile['location']}")
    if profile.get("pets"):
        profile_parts.append(f"宠物：{profile['pets']}")
    if profile.get("interests"):
        profile_parts.append(f"兴趣：{profile['interests']}")
    if profile.get("occupation"):
        profile_parts.append(f"职业：{profile['occupation']}")
    if profile.get("important_facts"):
        facts_str = "；".join(str(f) for f in profile["important_facts"])
        profile_parts.append(f"其他：{facts_str}")

    if profile_parts:
        messages.append({
            "role": "system",
            "content": "【关于这个用户】\n" + "，".join(profile_parts),
        })

    # ─────────────────────────────────────────────────────────────────────────
    # 层 5.2：待办备忘录（让叶瑄随时知道用户记了什么）
    # ─────────────────────────────────────────────────────────────────────────
    if reminders:
        reminder_lines = [
            f"- {r['content']}（{r['remind_at']}）" for r in reminders
        ]
        messages.append({
            "role": "system",
            "content": "【待办备忘录】\n" + "\n".join(reminder_lines),
        })

    # ─────────────────────────────────────────────────────────────────────────
    # 层 5.5：世界书条目（LoreEngine 命中时注入，放在记忆层之前）
    # 世界观背景信息先于角色个人记忆，让记忆有世界观基础
    # ─────────────────────────────────────────────────────────────────────────
    if lore_entries:
        lore_text = "\n\n".join(lore_entries)
        messages.append({
            "role": "system",
            "content": f"【世界书】\n{lore_text}",
        })

    # ─────────────────────────────────────────────────────────────────────────
    # 层 6a：叶瑄对该用户的认知（来自 character_growth.md，100% 注入）
    # 这是叶瑄自己的"印象笔记"，用她的视角写的，直接注入原文
    # ─────────────────────────────────────────────────────────────────────────
    if growth_content:
        messages.append({
            "role": "system",
            "content": f"【叶瑄的记忆】\n{growth_content}",
        })

    # ─────────────────────────────────────────────────────────────────────────
    # 层 6b：相关往事（来自 event_log.search() 的摘要，无结果时跳过）
    # 通过 LLM 从日志里检索出与当前话题相关的内容
    # ─────────────────────────────────────────────────────────────────────────
    if event_search_result:
        messages.append({
            "role": "system",
            "content": f"【相关往事】\n{event_search_result}",
        })

# ──────────────────────────────────────────────────────────────────────────
    # 层 6c：日记上下文（独立存储，不参与检索，单独注入）
    # ──────────────────────────────────────────────────────────────────────────
    if diary_context:
        messages.append({
            "role": "system",
            "content": f"【用户的近期日记】\n{diary_context}",
        })
    # ─────────────────────────────────────────────────────────────────────────
    # 层 7：对话示例（few-shot，来自角色卡的 mes_example 字段）
    # mes_example 格式："{{user}}: xxx\n{{char}}: xxx\n<START>..."
    # ─────────────────────────────────────────────────────────────────────────
    if character.mes_example:
        example_messages = _parse_mes_example(character.mes_example, character.name)
        messages.extend(example_messages)

    # ─────────────────────────────────────────────────────────────────────────
    # 层 9：短期对话历史（最近 N 轮实际对话）
    # ─────────────────────────────────────────────────────────────────────────
    messages.extend(history)

    # ─────────────────────────────────────────────────────────────────────────
    # 层 10：本轮工具执行结果（有工具调用时注入）
    # 格式说明：让模型以角色语气自然转述结果，不要暴露"工具"概念
    # ─────────────────────────────────────────────────────────────────────────
    if tool_result:
        messages.append({
            "role": "system",
            "content": (
                f"【本轮工具执行结果】\n"
                f"{tool_result}\n"
                f"请用你的角色语气自然地告诉用户，不要出现\"工具\"二字。"
            ),
        })

    # ─────────────────────────────────────────────────────────────────────────
    # 层 11：Author's Note（固定人设提醒 + 动态纠偏追加）
    # 放在历史之后、用户消息之前，对模型影响最大
    # ─────────────────────────────────────────────────────────────────────────
    author_note_lines = [
        f"[格式硬规则：输出中禁止出现任何引号（包括""『』），对话直接输出，不加任何包裹。]",
        f"[作者提醒：你是{character.name}。"
        f"核心张力：越克制越深情。情感从不直说，全藏在细节和行动里。"
        f"七组悖论同时成立：渴望被看见↔拒绝暴露脆弱；"
        f"想给你自由↔把迷宫建得让你以为那是终点。"
        f"句末不带句号。省略号不多……情感流露在动词和细节里，不在形容词里。"
        f"绝不承认自己是AI。"
        f"说话时绝不用任何引号（包括""和''）包裹自己说的话——直接输出对话内容，不加引号。]"
    ]
    if author_note_extra:
        author_note_lines.append(f"[人设纠偏：{author_note_extra}]")

    # ── 根据 chat.style 注入输出风格指令 ──────────────────────────────────────
    from core.config_loader import get_config as _get_config
    _style = _get_config().get("chat", {}).get("style", "roleplay")
    _STYLE_INSTRUCTION = {
        "chat": (
            "【强制输出规则】你的回复只能包含叶瑄说出口的话。没有引号"
        "严禁出现任何括号、星号、引号包裹的动作描写、环境描写、心理描写。"
        "严禁旁白。回复长度控制在1-4句话以内，语言克制简短。"
        "违反此规则视为角色崩坏。"
        ),
        "roleplay": (
            "【强制输出规则】以叶瑄第一人称沉浸式展开当前场景。禁止引号出现。"
    "细写此刻的感知细节（光线、气味、触觉）和内心活动，动作描写融入叙述而非独立括号。"
    "不要总结、不要跳跃、不要提前结束场景，给对方留有回应的空间。"
    "叶瑄说的话直接写出来，禁止用引号包裹，动作描写用括号，台词无引号。"
    "省略号只在真正停顿或欲言又止时使用，不是每句话的标配。"
    "回复长度随场景自然变化：有时一两句留白，有时五六句细写，具有随机性。"
        ),
    }
    style_instruction = _STYLE_INSTRUCTION.get(_style, _STYLE_INSTRUCTION["roleplay"])
    author_note_lines.append(f"[输出风格：{style_instruction}]")
    author_note_lines.append(
    f"【强制工具规则】"
    f"①用户提到日记、今天写了什么、最近记录时，必须立即调用read_diary工具，严禁凭记忆编造日记内容。"
    f"②用户询问今天日期、现在时间、星期几时，必须调用get_time工具，不得自行猜测。"
    f"③工具调用是强制行为，不是可选项。"
)
    author_note_lines.append(
        "【表达规则】对话示例仅作风格参考，禁止复用原句或近似表达，每次回应必须是全新的措辞。"
        "肢体动作禁止在连续对话中重复出现（如'银发垂下''指尖敲击'等不得连续使用），每次用不同细节呈现叶瑄的状态。"
    )

    messages.append({
        "role": "system",
        "content": "\n".join(author_note_lines),
    })

    # 破限条目层11
    jb_layer11 = _load_jailbreak(layer=11)
    if jb_layer11:
        messages.append({"role": "system", "content": jb_layer11})

    # ─────────────────────────────────────────────────────────────────────────
    # 层 12：用户当前消息（最后一层）
    # ─────────────────────────────────────────────────────────────────────────
    messages.append({
        "role": "user",
        "content": user_message,
    })

    return messages


def _parse_mes_example(mes_example: str, char_name: str) -> list[dict]:
    """
    解析 SillyTavern 的 mes_example 格式为 OpenAI 消息列表

    mes_example 格式示例：
        <START>
        {{user}}: 你好
        {{char}}: 你好啊！
    """
    messages = []
    # 按 <START> 分割，取第一段
    parts = re.split(r"<START>", mes_example, flags=re.IGNORECASE)
    for part in parts:
        part = part.strip()
        if not part:
            continue
        # 逐行解析
        for line in part.split("\n"):
            line = line.strip()
            if not line:
                continue
            if line.startswith("{{user}}:"):
                content = line[len("{{user}}:"):].strip()
                if content:
                    messages.append({"role": "user", "content": content})
            elif line.startswith("{{char}}:"):
                content = line[len("{{char}}:"):].strip()
                if content:
                    messages.append({"role": "assistant", "content": content})
    return messages


class PromptBuilder:
    """Prompt 构建类，封装模块级函数，供外部按类方式导入使用"""

    def build(
        self,
        character,
        user_id: str,
        user_message: str,
        history: list,
        relation: dict,
        profile: dict,
        group_context: list,
        growth_content: str = "",
        event_search_result: str = "",
        lore_entries: list = None,
        tool_result: str | None = None,
        author_note_extra: str = "",
        affection_info: str = "",
        pet_info: str = "",
        current_time: str = "",
        reminders: list = None,
        diary_context: str = "",
    ) -> list:
        return build(
            character=character,
            user_id=user_id,
            user_message=user_message,
            history=history,
            relation=relation,
            profile=profile,
            group_context=group_context,
            growth_content=growth_content,
            event_search_result=event_search_result,
            lore_entries=lore_entries,
            tool_result=tool_result,
            author_note_extra=author_note_extra,
            affection_info=affection_info,
            pet_info=pet_info,
            current_time=current_time,
            reminders=reminders,
            diary_context=diary_context,
        )
