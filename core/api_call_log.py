"""Fail-open ledger for outbound API calls; never stores request bodies or secrets."""
from __future__ import annotations

import time
from collections import Counter
from datetime import datetime, timedelta

from core.safe_write import safe_append_jsonl
from core.sandbox import get_paths

_KEEP_N = 7


def _daily_path(base_path, ts: float) -> object:
    day = datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
    return base_path.with_name(f"{base_path.stem}-{day}{base_path.suffix}")


def _prune_daily_logs(base_path, now: float) -> None:
    cutoff = (datetime.fromtimestamp(now).date() - timedelta(days=_KEEP_N - 1))
    pattern = f"{base_path.stem}-*{base_path.suffix}"
    for candidate in base_path.parent.glob(pattern):
        day = candidate.stem.removeprefix(f"{base_path.stem}-")
        try:
            if datetime.strptime(day, "%Y-%m-%d").date() < cutoff:
                candidate.unlink()
        except (OSError, ValueError):
            continue


def append(
    *,
    caller: str,
    purpose: str,
    provider: str,
    model: str,
    duration_ms: int,
    ok: bool,
    output_hint: str = "",
    request_id: str = "",
    audit_id: str = "",
) -> None:
    try:
        now = time.time()
        path = _daily_path(get_paths().api_call_log(), now)
        safe_append_jsonl(path, {
            "ts": now,
            "caller": caller,
            "purpose": purpose,
            "provider": provider,
            "model": model,
            "duration_ms": max(0, int(duration_ms)),
            "ok": bool(ok),
            "output_hint": str(output_hint)[:120],
            "request_id": str(request_id)[:128],
            "audit_id": str(audit_id)[:128],
        })
        _prune_daily_logs(get_paths().api_call_log(), now)
    except Exception:
        pass


def query(*, caller: str = "", provider: str = "", limit: int = 100) -> tuple[list[dict], dict[str, int]]:
    import json
    try:
        base_path = get_paths().api_call_log()
        paths = [base_path] + sorted(base_path.parent.glob(f"{base_path.stem}-*{base_path.suffix}"))
        paths = [path for path in paths if path.exists()]
        if not paths:
            return [], {}
        rows = [
            json.loads(line)
            for path in paths
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        rows = [
            r for r in rows
            if isinstance(r, dict)
            and (not caller or r.get("caller") == caller)
            and (not provider or r.get("provider") == provider)
        ]
        rows = sorted(rows, key=lambda row: float(row.get("ts") or 0), reverse=True)[:limit]
        return rows, dict(Counter(str(r.get("provider") or "unknown") for r in rows))
    except Exception:
        return [], {}
