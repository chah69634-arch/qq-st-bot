"""
角色卡加载模块
解析 SillyTavern 格式的角色卡 JSON 文件
支持角色一致性检测
"""

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from core.config_loader import get_config
from core.error_handler import log_error

logger = logging.getLogger(__name__)

CHARACTERS_DIR = Path("characters")

# 一致性检测计数器：{character_name: 轮次计数}
_consistency_counter: dict[str, int] = {}


@dataclass
class Character:
    """角色卡数据类，对应 SillyTavern 的核心字段"""
    name: str = "AI"
    description: str = ""        # 外貌/背景描述
    personality: str = ""        # 性格描述
    scenario: str = ""           # 当前情境/场景
    mes_example: str = ""        # 对话示例（few-shot）
    first_mes: str = ""          # 首次发言
    system_prompt: str = ""      # 全局 system 提示
    world_book: list[dict] = field(default_factory=list)  # 世界书条目


def load(filename: str) -> Character:
    """
    加载角色卡文件，支持三种格式：

    - .json  — SillyTavern 格式，解析各字段
    - .txt   — 纯文本，全文作为 description，文件名（去后缀）作为 name
    - .md    — 同 .txt，全文作为 description

    参数:
        filename: characters/ 目录下的文件名，如 "叶瑄.json" 或 "叶瑄.txt"

    返回:
        Character 对象；加载失败时返回默认空角色
    """
    path = CHARACTERS_DIR / filename
    suffix = Path(filename).suffix.lower()

    try:
        # ── 纯文本 / Markdown 格式 ────────────────────────────────────────────
        if suffix in (".txt", ".md"):
            text = path.read_text(encoding="utf-8")
            name = Path(filename).stem  # 文件名去掉后缀作为角色名
            char = Character(
                name=name,
                description=text,
            )
            logger.info(f"[character_loader] 角色 '{name}' 加载成功（纯文本格式）")
            return char

        # ── JSON 格式（原有逻辑） ─────────────────────────────────────────────
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        char = Character(
            name=data.get("name", "AI"),
            description=data.get("description", ""),
            personality=data.get("personality", ""),
            scenario=data.get("scenario", ""),
            mes_example=data.get("mes_example", ""),
            first_mes=data.get("first_mes", ""),
            system_prompt=data.get("system_prompt", ""),
            world_book=data.get("world_book", []),
        )
        logger.info(f"[character_loader] 角色 '{char.name}' 加载成功")
        return char

    except FileNotFoundError:
        logger.error(f"[character_loader] 角色文件不存在: {path}")
    except json.JSONDecodeError as e:
        logger.error(f"[character_loader] 角色文件 JSON 解析失败: {e}")
    except Exception as e:
        log_error("character_loader.load", e)

    # 返回最基础的默认角色，避免程序崩溃
    return Character(name="AI", system_prompt="你是一个友好的AI助手。")


async def consistency_check(character: Character, last_reply: str) -> dict:
    """
    检查最近一条回复是否符合角色人设

    每 consistency_check_every_n 轮调用一次
    返回：{"ok": bool, "issue": str}
    ok=False 时，issue 包含纠偏提示，将追加到下一轮的 Author's Note
    """
    cfg = get_config()
    check_every = cfg.get("character", {}).get("consistency_check_every_n", 15)
    char_name = character.name

    # 计数
    _consistency_counter[char_name] = _consistency_counter.get(char_name, 0) + 1
    if _consistency_counter[char_name] < check_every:
        return {"ok": True, "issue": ""}

    # 到达检测轮次，重置计数器
    _consistency_counter[char_name] = 0

    # 构建检测 prompt
    prompt_messages = [
        {
            "role": "system",
            "content": (
                "你是一个角色扮演一致性检查员。\n"
                "判断以下角色的最新回复是否符合其人设描述。\n"
                "只返回 JSON，格式：{\"ok\": true/false, \"issue\": \"如果不符合，用一句话描述问题和纠正方向\"}\n"
                "如果符合，issue 填空字符串。"
            ),
        },
        {
            "role": "user",
            "content": (
                f"角色名：{character.name}\n"
                f"性格描述：{character.personality}\n\n"
                f"最新回复：{last_reply}"
            ),
        },
    ]

    try:
        from core import llm_client
        import json as _json

        raw = await llm_client.chat(prompt_messages)
        raw = raw.strip().strip("```json").strip("```").strip()
        result = _json.loads(raw)
        if not result.get("ok"):
            logger.info(f"[consistency_check] 角色 {char_name} 发现人设偏离: {result.get('issue')}")
        return result
    except Exception as e:
        log_error("character_loader.consistency_check", e)
        return {"ok": True, "issue": ""}


def should_check_consistency(character: Character) -> bool:
    """
    非阻塞地判断是否达到检测轮次
    与 consistency_check 分离，方便在 main.py 中决定是否异步触发
    """
    cfg = get_config()
    check_every = cfg.get("character", {}).get("consistency_check_every_n", 15)
    char_name = character.name
    current = _consistency_counter.get(char_name, 0)
    return (current + 1) >= check_every


class CharacterLoader:
    """角色卡加载类，封装模块级函数，供外部按类方式导入使用"""

    def load(self, filename: str) -> Character:
        return load(filename)

    async def consistency_check(self, character: Character, last_reply: str) -> dict:
        return await consistency_check(character, last_reply)

    def should_check_consistency(self, character: Character) -> bool:
        return should_check_consistency(character)
