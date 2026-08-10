"""Pure projections for solo Scenario Dream script injection.

This module only formats an already-authored scenario script.  It does not
mutate the script, Character, Dream state, or any Reality-side store.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

PROJECTION_VERSION = "scenario-full-script-v1"
DEFAULT_MAX_STAGES = 12
DEFAULT_MAX_TOKENS = 6000
DEFAULT_MAX_CHARS = 24000
TOKENS_PER_CHAR = 4


def _limits() -> dict[str, int]:
    result = {
        "max_stages": DEFAULT_MAX_STAGES,
        "max_tokens": DEFAULT_MAX_TOKENS,
        "max_chars": DEFAULT_MAX_CHARS,
    }
    try:
        from core.config_loader import get_config

        raw = (get_config() or {}).get("dream", {}).get("scenario", {})
        if isinstance(raw, dict):
            for key in result:
                value = raw.get(f"full_script_{key.removeprefix('max_')}")
                if value is not None:
                    result[key] = max(1, int(value))
    except Exception:
        pass
    return result


def _lines(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    return [text] if text else []


def _append_field(parts: list[str], label: str, value: Any) -> None:
    if isinstance(value, list):
        values = _lines(value)
        parts.append(f"{label}:\n" + "\n".join(f"- {item}" for item in values))
    elif isinstance(value, dict):
        parts.append(f"{label}: {value}")
    else:
        text = str(value or "").strip()
        parts.append(f"{label}: {text}")


def render_full_script(script: dict[str, Any], current_stage_id: str) -> str:
    """Render every ordered stage and all private truth disclosure rules."""
    if not isinstance(script, dict):
        return ""
    stages = script.get("stages") or []
    if not isinstance(stages, list) or not stages:
        return ""

    parts = [
        "SCENARIO DIRECTOR MODE: FULL SCRIPT",
        "Follow the authored order. The current stage is authoritative.",
        "You may act toward the next stage, but you cannot skip stages, choose a later stage, or rewrite the stage order.",
        f"Title: {str(script.get('title') or script.get('id') or '').strip()}",
    ]
    if str(script.get("author") or "").strip():
        parts.append(f"Author: {str(script['author']).strip()}")

    current_index = next(
        (index for index, stage in enumerate(stages) if isinstance(stage, dict) and stage.get("id") == current_stage_id),
        None,
    )
    ordinal = f"{current_index + 1}/{len(stages)}" if current_index is not None else f"?/{len(stages)}"
    parts.append(f"CURRENT STAGE ID: {current_stage_id}; sequence: {ordinal}")

    for index, stage in enumerate(stages, start=1):
        if not isinstance(stage, dict):
            continue
        stage_id = str(stage.get("id") or "").strip()
        parts.append(f"\nSTAGE {index} | id={stage_id} | name={str(stage.get('name') or '').strip()}")
        _append_field(parts, "dramatic_task", stage.get("dramatic_task"))
        _append_field(parts, "entry_pressure", stage.get("entry_pressure"))
        _append_field(parts, "exit_signs", stage.get("exit_signs") or [])
        _append_field(parts, "not_yet_allowed", stage.get("not_yet_allowed") or [])
        if stage.get("drift_pressure"):
            _append_field(parts, "drift_pressure", stage.get("drift_pressure"))

    private_truths = script.get("private_truths") or []
    if private_truths:
        parts.append("\nPRIVATE TRUTHS AND DISCLOSURE POLICY")
        for item in private_truths:
            if not isinstance(item, dict):
                continue
            parts.append(f"truth_id={str(item.get('id') or '').strip()}")
            _append_field(parts, "truth", item.get("truth"))
            _append_field(parts, "disclosure", item.get("disclosure") or {})

    return "\n".join(parts).strip()


def estimate_script(script: dict[str, Any]) -> dict[str, int]:
    """Return bounded, non-content metadata for a complete script."""
    stages = script.get("stages") if isinstance(script, dict) else []
    stage_count = len(stages) if isinstance(stages, list) else 0
    text = render_full_script(script, str((stages[0] or {}).get("id") or "")) if stage_count else ""
    chars = len(text)
    return {
        "stage_count": stage_count,
        "estimated_chars": chars,
        "estimated_tokens": (chars + TOKENS_PER_CHAR - 1) // TOKENS_PER_CHAR,
    }


def full_script_budget(script: dict[str, Any]) -> dict[str, Any]:
    estimate = estimate_script(script)
    limits = _limits()
    reasons: list[str] = []
    if estimate["stage_count"] > limits["max_stages"]:
        reasons.append("stage_count_exceeded")
    if estimate["estimated_tokens"] > limits["max_tokens"]:
        reasons.append("token_budget_exceeded")
    if estimate["estimated_chars"] > limits["max_chars"]:
        reasons.append("char_budget_exceeded")
    return {
        **estimate,
        **limits,
        "ok": not reasons,
        "reasons": reasons,
        "projection_version": PROJECTION_VERSION,
    }


def scenario_projection_metadata(
    scenario_core: dict[str, Any], *, injection_mode: str = "strict_stage"
) -> dict[str, Any]:
    """Return safe Inspector fields without authored text or private truths."""
    result: dict[str, Any] = {
        "mode": injection_mode if injection_mode in {"strict_stage", "full_script"} else "strict_stage",
        "projection_version": PROJECTION_VERSION,
        "stage_count": 0,
        "estimated_chars": 0,
        "estimated_tokens": 0,
        "budget_ok": True,
        "budget_reasons": [],
    }
    try:
        from core.dream.scenario_loader import load_script

        script = load_script(str(scenario_core.get("script_id") or ""))
        budget = full_script_budget(script)
        result.update({
            "stage_count": budget["stage_count"],
            "estimated_chars": budget["estimated_chars"],
            "estimated_tokens": budget["estimated_tokens"],
            "budget_ok": budget["ok"],
            "budget_reasons": list(budget["reasons"]),
        })
    except Exception as exc:
        logger.debug("[scenario_projection] metadata unavailable: %s", exc)
    return result


def validate_full_script_budget(script: dict[str, Any]) -> dict[str, Any]:
    """Compatibility-named budget check used at scenario entry."""
    return full_script_budget(script)
