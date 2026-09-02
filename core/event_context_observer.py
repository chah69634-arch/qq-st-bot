"""Content-free, opt-in observability for EventContext propagation."""
from __future__ import annotations

from collections import Counter
from pathlib import Path
import hashlib
import json
import logging
import math
import threading
import time
from typing import Any

from core.safe_write import safe_append_jsonl
from core.sandbox import get_paths

logger = logging.getLogger(__name__)
_COUNTS: Counter[str] = Counter()
_LATEST: dict[str, Any] = {}
_LOCK = threading.RLock()
_MAX_TRACE_ROWS = 100_000


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


def _chain_key(value: object) -> str:
    clean = str(value or "").strip()
    if not clean:
        return ""
    return hashlib.sha256(clean.encode("utf-8")).hexdigest()[:20]


def record(
    *,
    stage: str,
    disposition: str,
    context=None,
    ingress_event_id: str = "",
    error_code: str = "",
    duplicate: bool = False,
    orphan: bool = False,
    scope_match: bool | None = None,
    started_at: float | None = None,
) -> None:
    """Append safe metadata only. This must never affect a runtime turn."""
    mode = config()["mode"]
    if mode == "disabled":
        return
    try:
        elapsed_ms = int(max(0.0, time.monotonic() - started_at) * 1000) if started_at else None
        resolved_ingress_id = ingress_event_id or str(getattr(context, "ingress_event_id", "") or "")
        actual_scope_match = bool(context and context.scope.domain == "reality")
        if scope_match is not None:
            actual_scope_match = bool(scope_match)
        row = {
            "ts": int(time.time()), "stage": str(stage)[:48], "disposition": str(disposition)[:48],
            "mode": mode, "chain_key": _chain_key(resolved_ingress_id),
            "scope_match": actual_scope_match,
            "causation_match": bool(context and context.causation_id == context.ingress_event_id),
            "has_turn": bool(context and context.turn_id), "duplicate": bool(duplicate), "orphan": bool(orphan),
            "latency_ms": elapsed_ms,
            "latency_bucket": (
                "not_measured" if elapsed_ms is None else
                "0-5" if elapsed_ms <= 5 else "6-20" if elapsed_ms <= 20 else "21+"
            ),
            "error_code": str(error_code)[:64],
            "source": str(getattr(context, "source", ""))[:48],
            "realm": str(getattr(getattr(context, "scope", None), "domain", ""))[:16],
        }
        with _LOCK:
            _COUNTS[f"{row['stage']}:{row['disposition']}"] += 1
            _LATEST.clear()
            _LATEST.update({
                key: row[key]
                for key in ("stage", "disposition", "mode", "error_code", "latency_bucket")
            })
            path = _trace_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            safe_append_jsonl(path, row)
    except Exception:
        logger.debug("[event_context_observer] trace write failed", exc_info=True)


def _percentile(values: list[int], percentile: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(percentile * len(ordered)) - 1))
    return ordered[index]


def _read_trace() -> tuple[list[dict[str, Any]], int, bool]:
    path = _trace_path()
    if not path.exists():
        return [], 0, False
    rows: list[dict[str, Any]] = []
    malformed = 0
    truncated = False
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if len(rows) >= _MAX_TRACE_ROWS:
                    truncated = True
                    break
                try:
                    row = json.loads(line)
                except (TypeError, ValueError):
                    malformed += 1
                    continue
                if isinstance(row, dict):
                    rows.append(row)
                else:
                    malformed += 1
    except OSError:
        return [], 1, False
    return rows, malformed, truncated


def snapshot() -> dict[str, Any]:
    cfg = config()
    try:
        from core.memory.event_store import observability_snapshot as _event_store_snapshot
        startup_readiness = _event_store_snapshot().get("startup_initialization", {})
    except Exception:
        startup_readiness = {"status": "unknown", "error_codes": {"snapshot_failed": 1}}
    rows, malformed, truncated = _read_trace()
    counts: Counter[str] = Counter()
    errors: Counter[str] = Counter()
    sources: Counter[str] = Counter()
    latency_values: dict[str, list[int]] = {}
    chains: dict[str, set[str]] = {}
    explicit_orphans: set[str] = set()
    latest: dict[str, Any] = {}
    for row in rows:
        stage = str(row.get("stage") or "unknown")
        disposition = str(row.get("disposition") or "unknown")
        counts[f"{stage}:{disposition}"] += 1
        error = str(row.get("error_code") or "")
        if error:
            errors[error] += 1
        source = str(row.get("source") or "unknown")
        sources[source] += 1
        latency = row.get("latency_ms")
        if isinstance(latency, int) and latency >= 0:
            latency_values.setdefault(stage, []).append(latency)
        key = str(row.get("chain_key") or "")
        if key:
            chains.setdefault(key, set()).add(f"{stage}:{disposition}")
            if bool(row.get("orphan")):
                explicit_orphans.add(key)
        latest = {
            key_name: row.get(key_name)
            for key_name in ("stage", "disposition", "mode", "error_code", "latency_bucket")
        }
    ingress_chains = {
        key for key, stages in chains.items()
        if "ingress:accepted" in stages
    }
    committed_chains = {
        key for key, stages in chains.items()
        if "evidence:committed" in stages
    }
    linked_chains = ingress_chains & committed_chains
    orphan_chains = (committed_chains - ingress_chains) | explicit_orphans
    latencies = {
        stage: {
            "count": len(values),
            "p50_ms": _percentile(values, 0.50),
            "p95_ms": _percentile(values, 0.95),
            "p99_ms": _percentile(values, 0.99),
            "max_ms": max(values) if values else None,
        }
        for stage, values in latency_values.items()
    }
    count = len(rows)
    return {
        "desired": cfg["mode"],
        # Brief 217-D has not opened enforcing. A hand-edited config remains
        # observable but cannot silently become a write-path gate.
        "effective_state": "observe" if cfg["mode"] == "enforcing" else cfg["mode"],
        "route": "backend-only",
        "startup_readiness": startup_readiness,
        "run_state": (
            "not_run" if not count else "running" if cfg["mode"] != "disabled" else "disabled_with_history"
        ),
        "trace": {
            "rows": count,
            "malformed_rows": malformed,
            "truncated": truncated,
            "first_ts": rows[0].get("ts") if rows else None,
            "last_ts": rows[-1].get("ts") if rows else None,
        },
        "counts": dict(counts),
        "errors": dict(errors),
        "sources": dict(sources),
        "chains": {
            "ingress": len(ingress_chains),
            "committed": len(committed_chains),
            "linked": len(linked_chains),
            "orphan": len(orphan_chains),
            "propagation_rate": (
                len(linked_chains) / len(committed_chains) if committed_chains else None
            ),
        },
        "latency": latencies,
        "latest": latest,
    }


def enforcing_readiness() -> dict[str, Any]:
    """Return the deterministic S1 gate used before enabling enforcement."""
    snap = snapshot()
    counts = snap.get("counts", {})
    chains = snap.get("chains", {})
    canonical_turns = sum(
        int(value or 0) for key, value in counts.items()
        if key == "evidence:committed"
    )
    stimuli = sum(
        int(value or 0) for key, value in counts.items()
        if key == "ingress:accepted"
    )
    errors = snap.get("errors", {})
    hard_failures = {
        key: int(errors.get(key, 0) or 0)
        for key in ("scope_mismatch", "realm_mismatch", "orphan", "duplicate_turn")
        if int(errors.get(key, 0) or 0) > 0
    }
    # S1 uses the later of the two sample thresholds.  Duration is deliberately
    # left to the operator; durable sample counts and hard red lines are safe to
    # evaluate automatically without trusting wall-clock timestamps.
    sample_ready = canonical_turns >= 200 and stimuli >= 100
    ready = sample_ready and not hard_failures and int(chains.get("orphan", 0) or 0) == 0
    missing = []
    if canonical_turns < 200:
        missing.append(f"canonical_turns:{canonical_turns}/200")
    if stimuli < 100:
        missing.append(f"stimuli:{stimuli}/100")
    if hard_failures:
        missing.append("hard_failures")
    if int(chains.get("orphan", 0) or 0):
        missing.append("orphan_chains")
    return {
        "ready": ready,
        "canonical_turns": canonical_turns,
        "stimuli": stimuli,
        "missing": missing,
        "hard_failures": hard_failures,
        "sample_rule": "canonical_turns>=200 and stimuli>=100",
    }


def reset_for_tests() -> None:
    _COUNTS.clear(); _LATEST.clear()
