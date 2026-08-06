"""
core/prompt_ablation.py — 层级消融开关（CC 任务 23 · B）

只过滤注入，不短路检索：fetch_context 照常执行所有召回，build_prompt 组装完毕后
统一按 disabled_layers 过滤掉对应 _layer 的消息。全局开关（单用户系统），进程内
热生效，无需重启。

fail-open：开关文件缺失/损坏 → 返回全启用默认值，绝不 raise。
"""
import json
import logging

logger = logging.getLogger(__name__)

ALWAYS_ON = {"1_system_prompt", "11_tool_grounding", "12_user_message"}  # 不可消融

# 进程内缓存 + 文件 mtime 失效检查
_cache: dict | None = None
_cache_mtime: float | None = None


def _read_raw() -> dict | None:
    from core.sandbox import get_paths
    path = get_paths().prompt_layer_ablation()
    if not path.exists():
        return None
    try:
        mtime = path.stat().st_mtime
    except OSError as exc:
        logger.warning("[prompt_ablation] stat 失败，视为全启用: %s", exc)
        return None
    global _cache, _cache_mtime
    if _cache is not None and _cache_mtime == mtime:
        return _cache
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("[prompt_ablation] 读取/解析失败，视为全启用: %s", exc)
        return None
    _cache = data
    _cache_mtime = mtime
    return data


def _active_char_disabled_layers() -> set:
    """活跃角色卡 presence_ext.disabled_layers（Brief 29 · 3.1）。

    不缓存：随角色切换即时生效。fail-soft：未注册/加载失败/字段缺失 → 空集合。
    """
    try:
        from core import pipeline_registry
        pl = pipeline_registry.get()
        char = pl.character if pl is not None else None
        if char is None:
            return set()
        return set(getattr(char, "presence_ext", {}).get("disabled_layers") or [])
    except Exception:
        return set()


def get_state() -> dict:
    """返回 {"disabled_layers": set(), "perception_block_disabled": bool}。

    disabled_layers 是全局开关文件 ∪ 活跃角色卡 presence_ext.disabled_layers（B29·3.1）。
    开关文件缺失/损坏时该部分 fail-open（视为空），角色卡部分仍照常合并。
    """
    data = _read_raw()
    char_layers = _active_char_disabled_layers()
    if data is None:
        return {"disabled_layers": char_layers, "perception_block_disabled": False}
    try:
        disabled = set(data.get("disabled_layers") or []) | char_layers
        perception_disabled = bool(data.get("perception_block_disabled", False))
        return {"disabled_layers": disabled, "perception_block_disabled": perception_disabled}
    except Exception as exc:
        logger.warning("[prompt_ablation] 状态字段解析失败，视为全启用: %s", exc)
        return {"disabled_layers": char_layers, "perception_block_disabled": False}


def set_state(disabled: list[str], perception_block_disabled: bool) -> dict:
    """写入新状态，原子写（tmp + os.replace），写后刷新缓存。

    disabled 与 ALWAYS_ON 有交集时 raise ValueError（路由层应转 422）。
    """
    overlap = set(disabled) & ALWAYS_ON
    if overlap:
        raise ValueError(f"不可消融层: {sorted(overlap)}")

    from datetime import datetime, timezone
    from core.sandbox import get_paths
    from core.safe_write import safe_write_json

    path = get_paths().prompt_layer_ablation()
    payload = {
        "disabled_layers": sorted(set(disabled)),
        "perception_block_disabled": bool(perception_block_disabled),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    ok = safe_write_json(path, payload, keep_bak=False)
    if not ok:
        raise RuntimeError(f"[prompt_ablation] 写入失败: {path}")

    global _cache, _cache_mtime
    try:
        _cache = payload
        _cache_mtime = path.stat().st_mtime
    except OSError:
        _cache = None
        _cache_mtime = None

    return {
        "disabled_layers": set(disabled),
        "perception_block_disabled": bool(perception_block_disabled),
    }
