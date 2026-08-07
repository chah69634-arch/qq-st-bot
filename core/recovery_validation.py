"""Read-only, no-outbound initialization checks for a restored instance."""
from __future__ import annotations

import json
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import yaml

from core.no_outbound import recovery_no_outbound
from core.sandbox import paths_for_installation


class RecoveryValidationError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@contextmanager
def _restored_cwd(root: Path) -> Iterator[None]:
    """Temporarily bind path/config singletons to the isolated restored tree."""
    previous = Path.cwd()
    import core.config_loader as config_loader
    import core.sandbox as sandbox

    saved = (config_loader._config, config_loader._base_config, config_loader._config_mtime, config_loader._base_config_mtime, sandbox._instance)
    os.chdir(root)
    config_loader._config = config_loader._base_config = None
    config_loader._config_mtime = config_loader._base_config_mtime = None
    sandbox._instance = None
    try:
        yield
    finally:
        os.chdir(previous)
        config_loader._config, config_loader._base_config, config_loader._config_mtime, config_loader._base_config_mtime, sandbox._instance = saved


def _validate_json_states(root: Path) -> tuple[int, int]:
    checked = dream_or_stage = 0
    for path in paths_for_installation(root).root_dir().rglob("*.json"):
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RecoveryValidationError("state_validation_failed", "恢复状态 JSON 无法读取。") from exc
        checked += 1
        if "dream" in path.as_posix().lower() or "stage" in path.as_posix().lower():
            dream_or_stage += 1
    return checked, dream_or_stage


def _has_live_absolute_reference(payload: object, live_root: Path) -> bool:
    live = str(live_root.resolve()).lower()
    if isinstance(payload, str):
        return live in payload.lower()
    if isinstance(payload, dict):
        return any(_has_live_absolute_reference(value, live_root) for value in payload.values())
    if isinstance(payload, list):
        return any(_has_live_absolute_reference(value, live_root) for value in payload)
    return False


def validate_restored_initialization(restored_root: Path, *, live_root: Path) -> dict[str, Any]:
    """Assemble real local dependencies without starting services or writing state."""
    restored_root = restored_root.resolve()
    try:
        config_payload = yaml.safe_load((restored_root / "config.yaml").read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise RecoveryValidationError("configuration_invalid", "恢复配置无法解析。") from exc
    if not isinstance(config_payload, dict):
        raise RecoveryValidationError("configuration_invalid", "恢复配置顶层必须是 mapping。")
    if _has_live_absolute_reference(config_payload, live_root):
        raise RecoveryValidationError("configuration_invalid", "恢复配置仍引用当前线上安装路径。")

    with _restored_cwd(restored_root), recovery_no_outbound() as guard:
        try:
            from core.config_loader import get_config
            cfg = get_config()
        except Exception as exc:
            raise RecoveryValidationError("configuration_invalid", "恢复配置无法由运行时加载。") from exc
        try:
            from admin.auth import get_admin_secret
            from admin.token_registry import list_records
            get_admin_secret()
            token_count = len(list_records())
        except Exception as exc:
            raise RecoveryValidationError("auth_initialization_failed", "恢复鉴权配置无法初始化。") from exc
        try:
            from core.sandbox import get_paths
            import core.character_loader as character_loader
            from core.asset_registry import AssetRegistry
            from core.lore_engine import LoreEngine
            paths = get_paths()
            active_path = paths.active_prompt_assets()
            active_id = ""
            if active_path.is_file():
                active_id = str(json.loads(active_path.read_text(encoding="utf-8")).get("active_character") or "")
            char_id = active_id or str(cfg.get("character", {}).get("default") or "")
            if not char_id:
                raise ValueError("missing active/default character")
            character = character_loader.load(char_id)
            assets = AssetRegistry()
            lore = LoreEngine()
            lore.load()
            if character.world_book:
                lore.load_entries(character.world_book)
        except Exception as exc:
            raise RecoveryValidationError("character_initialization_failed", "恢复角色或 authored 资产无法初始化。") from exc
        try:
            from core.pipeline import Pipeline
            Pipeline(character, lore, active_character_id=char_id)
        except Exception as exc:
            raise RecoveryValidationError("pipeline_initialization_failed", "恢复 Pipeline 无法装配。") from exc
        state_files, dream_state_files = _validate_json_states(restored_root)
        if guard.attempts:
            raise RecoveryValidationError("outbound_attempted", "恢复验证出现被阻止的外发尝试。")
    return {
        "configuration": "ok",
        "auth_initialization": "ok",
        "token_records": token_count,
        "character_initialization": "ok",
        "pipeline_initialization": "ok",
        "authored_asset_validation": "ok",
        "state_validation": "ok",
        "state_files_checked": state_files,
        "dream_or_stage_state_files_checked": dream_state_files,
        "outbound_attempts_blocked": 0,
    }
