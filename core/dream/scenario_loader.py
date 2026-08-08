"""
Scenario script loader.

Scripts are private authored content. Canonical writes live in
userdata/characters/dream/scenarios/{script_id}.yaml; the historical
data/dream/scenarios root remains a read-only fallback.
_SCRIPTS_BASE can still be monkeypatched in focused tests.

Minimal schema (v0):
  id:    str
  title: str
  stages:
    - id:               str
      name:             str
      dramatic_task:    str
      entry_pressure:   str
      exit_signs:       list[str]        # optional
      not_yet_allowed:  list[str]        # optional
"""
import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_SCRIPTS_BASE: Path | None = None
_SAFE_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


def _script_path(script_id: str) -> Path:
    if _SCRIPTS_BASE is not None:
        return _SCRIPTS_BASE / f"{script_id}.yaml"
    from core.sandbox import get_paths

    primary, fallback = get_paths().dream_scenario_read_dirs()
    candidate = primary / f"{script_id}.yaml"
    if candidate.exists():
        return candidate
    if fallback is not None:
        return fallback / f"{script_id}.yaml"
    return candidate


def load_script(script_id: str) -> dict[str, Any]:
    """
    Load a scenario script by id.
    Raises FileNotFoundError if missing, ValueError if schema invalid.
    """
    if not _SAFE_ID_RE.match(script_id):
        raise ValueError(f"invalid script_id: {script_id!r}")
    path = _script_path(script_id)
    if not path.exists():
        raise FileNotFoundError(f"scenario script not found: {path}")
    try:
        import yaml
        text = path.read_text(encoding="utf-8")
        data = yaml.safe_load(text)
    except Exception as exc:
        raise ValueError(f"scenario script {script_id!r} unreadable: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"scenario script {script_id!r} must be a YAML mapping")
    _validate_script(data)
    return data


def get_stage(script: dict[str, Any], stage_id: str) -> dict[str, Any] | None:
    """Return the stage dict matching stage_id, or None if not found."""
    for stage in (script.get("stages") or []):
        if stage.get("id") == stage_id:
            return stage
    return None


def get_next_stage(script: dict[str, Any], current_stage_id: str) -> dict[str, Any] | None:
    """Return the stage immediately after current_stage_id in script order.

    Returns None when current_stage_id is the last stage.
    Raises ValueError when current_stage_id is not found in the script (fail-loud).
    """
    stages = script.get("stages") or []
    for i, stage in enumerate(stages):
        if stage.get("id") == current_stage_id:
            if i + 1 < len(stages):
                return stages[i + 1]
            return None
    raise ValueError(
        f"stage {current_stage_id!r} not found in script {script.get('id')!r}"
    )


def _validate_script(data: dict[str, Any]) -> None:
    if not data.get("id"):
        raise ValueError("script missing 'id'")
    if not data.get("title"):
        raise ValueError("script missing 'title'")
    stages = data.get("stages")
    if not stages or not isinstance(stages, list):
        raise ValueError("script must have at least one stage")
    for i, stage in enumerate(stages):
        for key in ("id", "name", "dramatic_task", "entry_pressure"):
            if not stage.get(key):
                raise ValueError(f"stage[{i}] missing '{key}'")
        dp = stage.get("drift_pressure")
        if dp is not None:
            if not isinstance(dp, dict):
                raise ValueError(f"stage[{i}].drift_pressure must be a mapping")
            if not isinstance(dp.get("after_turns"), int):
                raise ValueError(f"stage[{i}].drift_pressure.after_turns must be int")
            if not isinstance(dp.get("instruction"), str) or not dp["instruction"].strip():
                raise ValueError(f"stage[{i}].drift_pressure.instruction must be non-empty str")
