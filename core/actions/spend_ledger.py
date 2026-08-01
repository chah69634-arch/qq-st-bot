"""Append-only mandate ledger for the non-autonomous spending boundary (Brief 57)."""
from __future__ import annotations

import json
import time
from datetime import datetime
from uuid import uuid4

from core.safe_write import safe_append_jsonl
from core.sandbox import get_paths

_STATUSES = frozenset({"proposed", "notified", "confirmed", "rejected", "capped", "observed", "check_failed"})


def read_ledger(limit: int | None = None) -> list[dict]:
    path = get_paths().spend_ledger()
    if not path.exists(): return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
            if isinstance(row, dict): rows.append(row)
        except json.JSONDecodeError: continue
    return rows[-limit:] if limit is not None else rows


def append(*, action: str, payee: str, amount: float, currency: str = "CNY", status: str,
           origin: str, mandate_id: str | None = None, note: str = "") -> dict | None:
    """Fail closed: return None when the immutable audit row cannot be persisted."""
    if status not in _STATUSES: raise ValueError("invalid spend status")
    row = {"ts": time.time(), "action": action, "payee": payee, "amount": float(amount),
           "currency": currency, "status": status, "origin": origin,
           "mandate_id": mandate_id or f"sp_{uuid4().hex}", "note": note[:240]}
    return row if safe_append_jsonl(get_paths().spend_ledger(), row) else None


def budget_usage(now: float | None = None) -> dict:
    now = time.time() if now is None else now
    current = datetime.fromtimestamp(now)
    daily = monthly = 0.0
    for row in read_ledger():
        if row.get("status") != "confirmed": continue
        try: when, amount = datetime.fromtimestamp(float(row["ts"])), float(row["amount"])
        except (KeyError, TypeError, ValueError): continue
        if when.date() == current.date(): daily += amount
        if (when.year, when.month) == (current.year, current.month): monthly += amount
    from core.config_loader import get_config
    cfg = get_config().get("spend", {})
    return {"enabled": bool(cfg.get("enabled", False)), "daily_used": daily, "monthly_used": monthly,
            "daily_cap": float(cfg.get("daily_cap", 0) or 0), "monthly_cap": float(cfg.get("monthly_cap", 0) or 0)}


def check_budget(action: str, payee: str, amount: float) -> tuple[bool, str]:
    from core.config_loader import get_config
    cfg = get_config().get("spend", {})
    if not cfg.get("enabled", False): return False, "disabled"
    if payee not in set(cfg.get("payee_whitelist") or []): return False, "payee_not_whitelisted"
    usage = budget_usage()
    if amount <= 0: return False, "invalid_amount"
    if usage["daily_used"] + amount > usage["daily_cap"]: return False, "daily_cap"
    if usage["monthly_used"] + amount > usage["monthly_cap"]: return False, "monthly_cap"
    return True, "ok"
