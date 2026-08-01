"""garden_tools — 角色维护花园时使用的内部浇水工具。"""

import logging

from core.config_loader import _char_name
from core.garden import manager as garden_manager
from core.garden.constants import FLOWERS

logger = logging.getLogger(__name__)

_FLOWER_NAMES = {f["id"]: f["name"] for f in FLOWERS}

_STAGE_CN = {
    "seed":    "种子",
    "sprout":  "嫩芽",
    "budding": "花苞",
    "bloom":   "盛开",
}


def _active_char_id() -> str | None:
    try:
        import json as _j
        from core.sandbox import get_paths
        raw = _j.loads(get_paths().active_prompt_assets().read_text(encoding="utf-8"))
        cid = (raw.get("active_character") or "").strip()
    except Exception:
        logger.warning("[garden_tools] active_prompt_assets 读取失败")
        return None

    if not cid:
        logger.warning("[garden_tools] active_character 为空")
        return None

    try:
        from core.asset_registry import get_registry
        get_registry().resolve(cid, "character")
    except ValueError:
        logger.warning("[garden_tools] active_character %r 不在注册表", cid)
        return None

    return cid


async def water_garden() -> str:
    """
    角色在对话上下文中决定维护花园时调用。角色会根据当前心情选择花园里对应那一株来浇。
    无参数，无冷却。返回一句给 LLM 的状态描述，角色基于这句话自然回复。
    """
    char = _char_name()
    char_id = _active_char_id()
    if char_id is None:
        return f"{char}想去浇水，但暂时找不到当前活跃角色，没浇成。"
    result = garden_manager.force_water(char_id=char_id)

    if not result.get("ok"):
        reason = result.get("reason", "unknown")
        logger.info("[garden tool] force_water failed: %s", result)
        if reason == "already_bloomed":
            return f"{char}走到花园，发现今天对应心情的那株花已经开了，暂时没什么需要浇的。"
        if reason == "no_slot_for_mood":
            mood = result.get("mood", "?")
            return f"{char}站在花园边愣了一下——此刻的心情（{mood}）好像找不到对应的那株花。"
        return f"{char}想去浇水，但花园那边出了点说不清的状况，没浇成。"

    flower_cn = _FLOWER_NAMES.get(result["flower_id"], result["flower_id"])
    stage_cn = _STAGE_CN.get(result["stage"], result["stage"])
    bloomed = result.get("bloomed", False)

    if bloomed:
        return f"{char}按当前的心情，去花园给{flower_cn}浇了水——它刚才开了。{char}看了一会儿，然后回来。"
    return f"{char}按当前的心情，去花园给{flower_cn}浇了一次水。它现在是{stage_cn}。"
