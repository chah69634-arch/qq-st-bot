"""Content-free, opt-in observability for EventContext propagation."""
from __future__ import annotations

from collections import Counter
from pathlib import Path
import logging
import time
from typing import Any

from core.safe_write import safe_append_jsonl
from core.sandbox import get_paths

logger = logging.getLogger(__name__)
_COUNTS: Counter[str] = Counter()
_LATEST: dict[str, Any] = {}


def config() -> dict[str, Any]:
    try:
        from core.config_loader import get_config
        raw = get_config().get("event_context_observer") or {}
    except Exception:
        raw = {}
    mode = str(raw.get("mode", "disabled")).lower()
    return {"mode": mode if mode in {"disabled", "observe", "enforcing"} else "disabled"}


def enabled() -> bool:
    return config()["mode"] != "disabled"


def _trace_path() -> Path:
    return get_paths().event_context_trace()


def record(*, stage: str, disposition: str, context=None, error_code: str = "", duplicate: bool = False,
           orphan: bool = False, started_at: float | None = None) -> None:
    """Append safe metadata only. This must never affect a runtime turn."""
    mode = config()["mode"]
    if mode == "disabled":
        return
    try:
        elapsed_ms = int(max(0.0, time.monotonic() - started_at) * 1000) if started_at else 0
        row = {
            "ts": int(time.time()), "stage": str(stage)[:48], "disposition": str(disposition)[:48],
            "mode": mode, "scope_match": bool(context and context.scope.domain == "reality"),
            "causation_match": bool(context and context.causation_id == context.ingress_event_id),
            "has_turn": bool(context and context.turn_id), "duplicate": bool(duplicate), "orphan": bool(orphan),
            "latency_bucket": "0-5" if elapsed_ms <= 5 else "6-20" if elapsed_ms <= 20 else "21+",
            "error_code": str(error_code)[:64],
            "source": str(getattr(context, "source", ""))[:48],
            "realm": str(getattr(getattr(context, "scope", None), "domain", ""))[:16],
        }
        _COUNTS[f"{row['stage']}:{row['disposition']}"] += 1
        if error_code:
            _COUNTS[f"error:{row['error_code']}"] += 1
        _LATEST.clear(); _LATEST.update({key: row[key] for key in ("stage", "disposition", "mode", "error_code", "latency_bucket")})
        path = _trace_path(); path.parent.mkdir(parents=True, exist_ok=True)
        safe_append_jsonl(path, row)
    except Exception:
        logger.debug("[event_context_observer] trace write failed", exc_info=True)


def snapshot() -> dict[str, Any]:
    cfg = config(); count = sum(_COUNTS.values())
    return {
        "desired": cfg["mode"],
        # Brief 217-D has not opened enforcing. A hand-edited config remains
        # observable but cannot silently become a write-path gate.
        "effective_state": "observe" if cfg["mode"] == "enforcing" else cfg["mode"],
        "route": "backend-only",
        "run_state": "running" if count else "not_run", "counts": dict(_COUNTS),
        "latest": dict(_LATEST),
    }


def reset_for_tests() -> None:
    _COUNTS.clear(); _LATEST.clear()
