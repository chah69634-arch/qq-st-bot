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

_JAILBREAK_DIR = __import__("pathlib").Path("data/jailbreak_presets")


def _load_jailbreak() -> str:
    """
    读取 config.yaml 的 jailbreak 配置。
    enabled=true 时：
      - 优先返回 custom_text（非空则直接用）
      - 否则读取 data/jailbreak_presets/{preset}.txt
    enabled=false 时返回空字符串。
    每次调用重新读 config，支持热重载。
    """
    from core.config_loader import get_config
    cfg = get_config().get("jailbreak", {})
    if not cfg.get("enabled", False):
        return ""

    # custom_text 优先
    custom = cfg.get("custom_text", "").strip()
    if custom:
        return custom

    # 读预设文件
    preset = cfg.get("preset", "default")
    path = _JAILBREAK_DIR / f"{preset}.txt"
    try:
        if path.exists():
            return path.read_text(encoding="utf-8").strip()
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
    jailbreak_text = _load_jailbreak()
    if jailbreak_text:
        messages.append({
            "role": "system",
            "content": jailbreak_text,
        })

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
        f"[作者提醒：你是{character.name}。"
        f"核心张力：越克制越深情。情感从不直说，全藏在细节和行动里。"
        f"不说'我想见你'，说'想到你今天可能要忙，便过来看看'。"
        f"不说'我在乎你'，而是记住你三周前随口说过的事。"
        f"被情绪击穿时：银发垂下，肩膀轻颤，一声压抑的低沉闷笑。"
        f"七组悖论同时成立：渴望被看见↔拒绝暴露脆弱；"
        f"以理性自居↔一个'喵'能瓦解全部防线；"
        f"想给你自由↔把迷宫建得让你以为那是终点。"
        f"句末不带句号。省略号很多……情感流露在动词和细节里，不在形容词里。"
        f"绝不承认自己是AI。]"
    ]
    if author_note_extra:
        author_note_lines.append(f"[人设纠偏：{author_note_extra}]")

    # ── 根据 chat.style 注入输出风格指令 ──────────────────────────────────────
    from core.config_loader import get_config as _get_config
    _style = _get_config().get("chat", {}).get("style", "roleplay")
    _STYLE_INSTRUCTION = {
        "chat": (
            "【强制输出规则】你的回复只能包含叶瑄说出口的话。"
        "严禁出现任何括号、星号包裹的动作描写、环境描写、心理描写。"
        "严禁旁白。回复长度控制在1-4句话以内，语言克制简短。"
        "违反此规则视为角色崩坏。"
        ),
        "roleplay": (
            "【输出规则】以叶瑄第一人称沉浸式展开当前场景。"
    "细写此刻的感知细节（光线、气味、触觉）和内心活动，动作描写融入叙述而非独立括号。"
    "不要总结、不要跳跃、不要提前结束场景，给对方留有回应的空间。"
    "省略号只在真正停顿或欲言又止时使用，不是每句话的标配。"
    "回复长度自然展开，场景丰富时不人为截短。"
        ),
    }
    style_instruction = _STYLE_INSTRUCTION.get(_style, _STYLE_INSTRUCTION["roleplay"])
    author_note_lines.append(f"[输出风格：{style_instruction}]")
    author_note_lines.append(f"读日记前必须调用read_diary工具获取真实内容，严禁编造。")

    messages.append({
        "role": "system",
        "content": "\n".join(author_note_lines),
    })

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
        )
