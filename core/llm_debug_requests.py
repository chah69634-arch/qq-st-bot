"""Explicit opt-in, admin-only semantic snapshots of outbound LLM requests.

This is deliberately separate from ``api_call_log``: the ordinary API ledger
never stores request bodies, while these snapshots contain prompt text and tool
schemas and are therefore disabled by default and restricted to admin readers.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timedelta
from typing import Any

from core.safe_write import safe_append_jsonl
from core.sandbox import get_paths

_DEFAULT_KEEP_DAYS = 1
_MAX_KEEP_DAYS = 7
_SENSITIVE_KEY_PARTS = ("api_key", "apikey", "authorization", "password", "secret", "token")


def _settings() -> tuple[bool, int]:
    try:
        from core.config_loader import get_config

        cfg = get_config().get("llm_debug_requests", {})
        if not isinstance(cfg, dict):
            return False, _DEFAULT_KEEP_DAYS
        keep_days = int(cfg.get("keep_days", _DEFAULT_KEEP_DAYS))
        return bool(cfg.get("enabled", False)), max(1, min(_MAX_KEEP_DAYS, keep_days))
    except Exception:
        return False, _DEFAULT_KEEP_DAYS


def _daily_path(base_path, ts: float):
    day = datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
    return base_path.with_name(f"{base_path.stem}-{day}{base_path.suffix}")


def _prune_daily_logs(base_path, keep_days: int, now: float) -> None:
    cutoff = datetime.fromtimestamp(now).date() - timedelta(days=keep_days - 1)
    pattern = f"{base_path.stem}-*{base_path.suffix}"
    for candidate in base_path.parent.glob(pattern):
        day = candidate.stem.removeprefix(f"{base_path.stem}-")
        try:
            if datetime.strptime(day, "%Y-%m-%d").date() < cutoff:
                candidate.unlink()
        except (OSError, ValueError):
            continue


def _redact(value: Any, *, key: str = "") -> Any:
    """Keep the semantic request while never persisting credentials or image bytes."""
    key_lower = key.lower()
    if any(part in key_lower for part in _SENSITIVE_KEY_PARTS):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(k): _redact(v, key=str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, str) and value.startswith("data:image/"):
        return "[REDACTED image data URL]"
    return value


def append(
    *,
    provider: str,
    model: str,
    purpose: str,
    messages: list[dict],
    tools: list[dict] | None,
    request_kwargs: dict[str, Any],
) -> None:
    """Fail-open append.  No caller should be delayed or failed by debugging."""
    enabled, keep_days = _settings()
    if not enabled:
        return
    try:
        now = time.time()
        path = _daily_path(get_paths().llm_debug_request_log(), now)
        snapshot = {
            "ts": now,
            "provider": str(provider),
            "model": str(model),
            "purpose": str(purpose),
            "messages": _redact(messages),
            "tools": _redact(tools or []),
            "request_kwargs": _redact(request_kwargs),
        }
        # Verify serializability before passing the payload to the writer.  The
        # SDK accepts a few non-JSON helper values (for example a timeout object);
        # rendering those as text keeps the snapshot useful without affecting calls.
        snapshot = json.loads(json.dumps(snapshot, ensure_ascii=False, default=str))
        safe_append_jsonl(path, snapshot)
        _prune_daily_logs(get_paths().llm_debug_request_log(), keep_days, now)
    except Exception:
        pass


def query(*, purpose: str = "", limit: int = 20) -> list[dict]:
    try:
        base_path = get_paths().llm_debug_request_log()
        paths = [base_path] + sorted(base_path.parent.glob(f"{base_path.stem}-*{base_path.suffix}"))
        rows = [
            json.loads(line)
            for path in paths
            if path.exists()
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        rows = [row for row in rows if isinstance(row, dict) and (not purpose or row.get("purpose") == purpose)]
        return sorted(rows, key=lambda row: float(row.get("ts") or 0), reverse=True)[:max(1, min(100, limit))]
    except Exception:
        return []
