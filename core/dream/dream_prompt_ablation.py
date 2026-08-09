"""Dream Prompt layer ablation switches.

This is deliberately separate from Reality ``core.prompt_ablation`` because
Dream uses a different layer vocabulary and assembly pipeline. The switch only
filters assembled prompt injection; loaders and dream-state computation still
run. Missing or malformed state fails open (all layers enabled).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

KNOWN_LAYERS: tuple[tuple[str, str], ...] = (
    ("D0_jailbreak", "Dream preset / jailbreak"),
    ("D1_identity_core", "Character card identity and Dream behavior"),
    ("DG_group_presence", "Group Dream in-scene presence"),
    ("D2_world_ruleset", "Dream world rules"),
    ("D3_mes_example", "Dream example dialogue"),
    ("D4_frozen_reality", "Frozen reality snapshot"),
    ("D4.5_hidden_state", "Read-only hidden-state snapshot"),
    ("D5_body_projection", "Dream body projection"),
    ("D6_scene_anchors", "Scene and symbolic anchors"),
    ("D7_dream_tension", "Character tension bucket"),
    ("D8_dream_director", "Dream rendering and director guidance"),
    ("DX_exit_protocol", "Hard and soft exit machine protocol (always on)"),
    ("DS_scenario", "Current scenario stage and action contract"),
    ("DM_mirror", "Mirror-mode symbolic material"),
    ("D_lorebook", "Matched Dream lorebook entries"),
    ("D9_dream_history", "Dream conversation history"),
    ("D10_user_message", "Current user message (always on)"),
)
ALWAYS_ON = frozenset({"DX_exit_protocol", "D10_user_message"})

_cache: dict | None = None
_cache_mtime: float | None = None


def get_state() -> dict[str, set[str]]:
    from core.sandbox import get_paths

    path = get_paths().dream_prompt_layer_ablation()
    if not path.exists():
        return {"disabled_layers": set()}
    try:
        mtime = path.stat().st_mtime
        global _cache, _cache_mtime
        if _cache is not None and _cache_mtime == mtime:
            data = _cache
        else:
            data = json.loads(path.read_text(encoding="utf-8"))
            _cache = data
            _cache_mtime = mtime
        disabled = set(data.get("disabled_layers") or [])
        return {"disabled_layers": disabled - ALWAYS_ON}
    except Exception as exc:
        logger.warning("[dream_prompt_ablation] read failed; all layers enabled: %s", exc)
        return {"disabled_layers": set()}


def set_state(disabled_layers: list[str]) -> dict[str, set[str]]:
    disabled = set(disabled_layers)
    known = {name for name, _ in KNOWN_LAYERS}
    unknown = disabled - known
    if unknown:
        raise ValueError(f"未知层名: {sorted(unknown)}")
    overlap = disabled & ALWAYS_ON
    if overlap:
        raise ValueError(f"不可消融层: {sorted(overlap)}")

    from core.safe_write import safe_write_json
    from core.sandbox import get_paths

    path = get_paths().dream_prompt_layer_ablation()
    payload = {
        "disabled_layers": sorted(disabled),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    if not safe_write_json(path, payload, keep_bak=False):
        raise RuntimeError(f"[dream_prompt_ablation] write failed: {path}")

    global _cache, _cache_mtime
    _cache = payload
    try:
        _cache_mtime = path.stat().st_mtime
    except OSError:
        _cache = None
        _cache_mtime = None
    return {"disabled_layers": disabled}
