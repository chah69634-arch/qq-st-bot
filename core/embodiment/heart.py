"""爱意探针 → 板子画爱心。gate + 冷却，fail-open。"""
from __future__ import annotations

import time
import logging

from core import config_loader, llm_client

logger = logging.getLogger(__name__)

_LAST_SENT: dict[str, float] = {}   # char_id → epoch


async def maybe_draw_heart(reply: str, char_id: str) -> None:
    cfg = config_loader.get_config().get("embodiment", {}).get("heart", {})
    if not cfg.get("enabled", False):
        return
    cooldown = float(cfg.get("cooldown_sec", 45))
    now = time.time()
    if now - _LAST_SENT.get(char_id, 0.0) < cooldown:
        return
    if not reply or not reply.strip():
        return
    try:
        if not await llm_client.detect_affection(reply):
            return
        from core.tool_dispatcher import _push_desktop_action
        result = await _push_desktop_action({
            "type": "show_heart",
            "duration_ms": int(cfg.get("duration_ms", 4000)),
        })
        if result == "ok":
            _LAST_SENT[char_id] = now
            logger.info("[heart] 爱意命中，设备已确认画爱心 char=%s", char_id)
        else:
            logger.debug("[heart] 爱意命中但设备动作未确认: %s", result)
    except Exception as e:
        logger.debug("[heart] skipped: %s", e)
