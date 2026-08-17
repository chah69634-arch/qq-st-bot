"""Read-only shadow evaluation for the Memory Event recall path.

The shadow path is deliberately separate from prompt construction.  It may
search and expand a bounded reality event window, but it returns only
content-free metrics and identifiers to the caller.  Any failure is a metric,
not a reason to alter the normal recall path.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any, Iterable

from core.config_loader import get_config
from core.memory import event_query
from core.memory.scope import MemoryScope

DEFAULTS: dict[str, Any] = {
    "enabled": False,
    "uids": [],
    "char_ids": [],
    "seed_limit": 3,
    "window_before": 2,
    "window_after": 2,
    "max_related_per_seed": 4,
    "timeout_ms": 120,
    "max_trace_ids": 24,
}


def config() -> dict[str, Any]:
    """Return bounded, hot-reloaded shadow settings."""
    try:
        raw = get_config().get("event_shadow_recall") or {}
    except Exception:
        raw = {}
    result = dict(DEFAULTS)
    if isinstance(raw, dict):
        result.update(raw)
    for key, low, high in (
        ("seed_limit", 1, 8),
        ("window_before", 0, 8),
        ("window_after", 0, 8),
        ("max_related_per_seed", 0, 8),
        ("timeout_ms", 20, 500),
        ("max_trace_ids", 1, 64),
    ):
        try:
            result[key] = min(high, max(low, int(result.get(key, DEFAULTS[key]))))
        except (TypeError, ValueError):
            result[key] = DEFAULTS[key]
    return result


def _values(raw: Any) -> set[str]:
    if isinstance(raw, str):
        return {raw.strip()} if raw.strip() else set()
    if isinstance(raw, (list, tuple, set, frozenset)):
        return {str(value).strip() for value in raw if str(value).strip()}
    return set()


def enabled_for(uid: str, char_id: str, cfg: dict[str, Any] | None = None) -> bool:
    """Resolve global plus uid/character rollout gates.

    ``uids``/``char_ids`` are allowlists and can enable a scope even when the
    global flag is false.  The two ``allow_*`` aliases are accepted for easy
    migration from deployment config drafts.
    """
    settings = cfg or config()
    if bool(settings.get("enabled", False)):
        return True
    return (
        str(uid) in (_values(settings.get("uids")) | _values(settings.get("allow_uids")))
        or str(char_id) in (_values(settings.get("char_ids")) | _values(settings.get("allow_char_ids")))
    )


def _event_id_set(values: Iterable[Any]) -> set[str]:
    result: set[str] = set()
    for value in values:
        if isinstance(value, dict):
            value = value.get("event_id") or value.get("id")
        elif isinstance(value, (list, tuple)):
            value = value[0] if value else ""
        if value:
            result.add(str(value))
    return result


def _jaccard(left: set[str], right: set[str]) -> float:
    union = left | right
    return round(len(left & right) / len(union), 4) if union else 0.0


def _text_size(event: dict[str, Any]) -> int:
    return len(str(event.get("memory_text") or event.get("visible_text") or ""))


def _in_scope(event: dict[str, Any], scope: MemoryScope) -> bool:
    return (
        str(event.get("uid") or "") == scope.uid
        and str(event.get("char_id") or "") == str(scope.character_id or "")
        and str(event.get("realm") or "") == scope.domain
    )


def _run_sync(scope: MemoryScope, query: str, old_ids: set[str], settings: dict[str, Any]) -> dict[str, Any]:
    started = time.perf_counter()
    seed_ids: list[str] = []
    new_ids: list[str] = []
    expanded_count = 0
    related_count = 0
    rejected_count = 0
    chars = 0
    truncation_reason = ""
    seeds = event_query.search(
        scope,
        text=str(query or "")[:256],
        actor="",
        kind="",
        source="",
        occurred_after=None,
        occurred_before=None,
        cursor="",
        limit=int(settings["seed_limit"]),
    )
    seen: set[str] = set()
    for item in seeds.get("items", []):
        if not _in_scope(item, scope):
            rejected_count += 1
            continue
        event_id = str(item.get("event_id") or "")
        if not event_id or event_id in seen:
            continue
        seen.add(event_id)
        seed_ids.append(event_id)
        new_ids.append(event_id)
        chars += _text_size(item)
        if len(new_ids) >= int(settings["max_trace_ids"]):
            truncation_reason = "trace_id_limit"
            break

    for event_id in list(seed_ids):
        if len(new_ids) >= int(settings["max_trace_ids"]):
            truncation_reason = truncation_reason or "trace_id_limit"
            break
        window = event_query.window(
            scope, event_id,
            before=int(settings["window_before"]),
            after=int(settings["window_after"]),
        )
        if not window:
            continue
        for item in [*window.get("before", []), *window.get("after", [])]:
            if not _in_scope(item, scope):
                rejected_count += 1
                continue
            expanded_count += 1
            related_id = str(item.get("event_id") or "")
            if related_id and related_id not in seen and len(new_ids) < int(settings["max_trace_ids"]):
                seen.add(related_id)
                new_ids.append(related_id)
                chars += _text_size(item)

        if int(settings["max_related_per_seed"]) <= 0:
            continue
        related = event_query.related(
            scope, event_id, cursor="", limit=int(settings["max_related_per_seed"]), relation_types=None,
        )
        for item in related.get("items", []) if related else []:
            event = item.get("event")
            if not event:
                continue
            if not _in_scope(event, scope):
                rejected_count += 1
                continue
            related_count += 1
            related_id = str(event.get("event_id") or "")
            if related_id and related_id not in seen and len(new_ids) < int(settings["max_trace_ids"]):
                seen.add(related_id)
                new_ids.append(related_id)
                chars += _text_size(event)

    if seeds.get("truncation_reason"):
        truncation_reason = truncation_reason or str(seeds["truncation_reason"])
    return {
        "status": "ok",
        "seed_event_ids": seed_ids,
        "new_event_ids": new_ids,
        "expand_count": expanded_count,
        "related_count": related_count,
        "candidate_count": len(new_ids),
        "chars": chars,
        "tokens": (chars + 3) // 4,
        "old_chars": 0,
        "old_tokens": 0,
        "overlap_rate": _jaccard(set(new_ids), old_ids),
        "scope_rejections": rejected_count,
        "truncation_reason": truncation_reason,
        "timeout_reason": "",
        "elapsed_ms": int((time.perf_counter() - started) * 1000),
    }


async def run_shadow_recall(
    scope: MemoryScope,
    query: str,
    *,
    old_ids: Iterable[Any] = (),
    old_chars: int = 0,
    settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run a bounded shadow query with a hard wall-clock budget."""
    cfg = config()
    if settings is not None:
        cfg.update(settings)
        for key, low, high in (
            ("seed_limit", 1, 8), ("window_before", 0, 8), ("window_after", 0, 8),
            ("max_related_per_seed", 0, 8), ("timeout_ms", 20, 500), ("max_trace_ids", 1, 64),
        ):
            try:
                cfg[key] = min(high, max(low, int(cfg[key])))
            except (TypeError, ValueError):
                cfg[key] = DEFAULTS[key]
    base = {
        "enabled": enabled_for(scope.uid, str(scope.character_id or ""), cfg),
        "status": "disabled",
        "seed_event_ids": [],
        "new_event_ids": [],
        "expand_count": 0,
        "related_count": 0,
        "candidate_count": 0,
        "chars": 0,
        "tokens": 0,
        "old_chars": max(0, int(old_chars)),
        "old_tokens": (max(0, int(old_chars)) + 3) // 4,
        "overlap_rate": 0.0,
        "scope_rejections": 0,
        "truncation_reason": "",
        "timeout_reason": "",
        "elapsed_ms": 0,
    }
    if not base["enabled"]:
        return base
    old_set = _event_id_set(old_ids)
    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(_run_sync, scope, query, old_set, cfg),
            timeout=float(cfg["timeout_ms"]) / 1000.0,
        )
        result["enabled"] = True
        result["timeout_reason"] = ""
        result["old_chars"] = max(0, int(old_chars))
        result["old_tokens"] = (max(0, int(old_chars)) + 3) // 4
        return result
    except asyncio.TimeoutError:
        base.update({"status": "timeout", "timeout_reason": "budget_exceeded"})
        return base
    except Exception as exc:
        base.update({"status": "error", "timeout_reason": type(exc).__name__[:64]})
        return base
