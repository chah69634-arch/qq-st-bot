"""Daily, notification-only API credit monitor. No payment credential or browser access exists here."""
from __future__ import annotations
import time
from core.actions import api_balance
from core.actions import spend_ledger

_COOLDOWN_SECONDS = 48 * 3600

def _recently_notified(payee: str) -> bool:
    now = time.time()
    return any(r.get("payee") == payee and r.get("status") == "notified" and now - float(r.get("ts", 0)) < _COOLDOWN_SECONDS
               for r in spend_ledger.read_ledger())


def _unconfirmed_notified_rows(payee: str) -> list[dict]:
    """Return only notifications whose mandate has not already recovered."""
    rows = spend_ledger.read_ledger()
    confirmed_ids = {
        row.get("mandate_id") for row in rows
        if row.get("status") == "confirmed" and row.get("mandate_id")
    }
    return [
        row for row in rows
        if row.get("payee") == payee
        and row.get("status") == "notified"
        and row.get("mandate_id") not in confirmed_ids
    ]

async def _notify(uid: str, text: str) -> bool:
    from channels import registry
    channel = registry.get("mobile")
    if channel is None: return False
    await channel.send(text, uid)
    return True

def _action_trace(uid: str, payee: str, char_id: str) -> None:
    try:
        from core.memory.action_trace import record
        record(uid, char_id, tool="api_topup", origin="scheduler", status="ok", result_digest=f"提醒 {payee} API 余额不足")
    except Exception: pass

def _observation_note(result: api_balance.BalanceResult) -> str:
    if result.available_cash_amount is None or result.available_amount is None:
        return f"balance={result.balance}"
    return (
        f"available_cash_amount={result.available_cash_amount}; "
        f"available_amount={result.available_amount}; selected={result.balance}"
    )


async def check_spend_monitor(*, force: bool = False) -> list[dict]:
    """Run only read-only balance checks; force is for the authenticated admin endpoint."""
    from core.config_loader import get_config
    from core.data_paths import DEFAULT_CHAR_ID
    from core.scheduler.loop import _is_ready, _mark, _owner_id
    if not force and not _is_ready("spend_monitor"):
        return []
    _mark("spend_monitor")
    cfg, uid = get_config().get("spend", {}), _owner_id()
    if not cfg.get("enabled", False):
        return [{"status": "disabled"}]
    outcomes: list[dict] = []
    for provider in cfg.get("balance_providers") or []:
        name = str(provider.get("name") or "").strip()
        if not name:
            continue
        result = await api_balance.fetch_balance_result(provider)
        if result is None:
            spend_ledger.append(action="balance_check", payee=name, amount=0, status="check_failed", origin="scheduler", note="balance unavailable")
            outcomes.append({"provider": name, "status": "unavailable"})
            continue
        threshold = provider.get("threshold")
        if threshold is None:
            outcomes.append({"provider": name, "status": "missing_threshold"})
            continue
        balance = result.balance
        observed = spend_ledger.append(
            action="balance_check",
            payee=name,
            amount=balance,
            currency=result.currency,
            status="observed",
            origin="scheduler",
            note=_observation_note(result),
        )
        if observed is None:
            outcomes.append({"provider": name, "status": "ledger_unavailable"})
            continue
        amount = float(provider.get("topup_amount", 0) or 0)
        if balance >= float(threshold):
            # A later healthy balance is the only v1 confirmation signal.
            for notified in _unconfirmed_notified_rows(name):
                spend_ledger.append(action="api_topup", payee=name, amount=float(notified.get("amount", amount) or 0), currency=result.currency, status="confirmed", origin="scheduler", mandate_id=notified["mandate_id"], note="balance recovered")
            outcomes.append({"provider": name, "status": "healthy"})
            continue
        if _recently_notified(name):
            outcomes.append({"provider": name, "status": "low_already_notified"})
            continue
        allowed, reason = spend_ledger.check_budget("api_topup", name, amount)
        if not allowed:
            spend_ledger.append(action="api_topup", payee=name, amount=amount, currency=result.currency, status="capped", origin="scheduler", note=reason)
            outcomes.append({"provider": name, "status": "low_capped"})
            continue
        proposal = spend_ledger.append(action="api_topup", payee=name, amount=amount, currency=result.currency, status="proposed", origin="scheduler", note=f"balance={balance}")
        if proposal is None:
            outcomes.append({"provider": name, "status": "ledger_unavailable"})
            continue
        if not uid:
            outcomes.append({"provider": name, "status": "low_no_owner"})
            continue
        link = str(provider.get("topup_url") or "")
        from core.character_name_provider import get_char_name
        text = f"{get_char_name()}提醒你：{name} API 余额低于阈值，请自行充值{('：' + link) if link else ''}。系统不会替你付款。"
        if await _notify(uid, text):
            spend_ledger.append(action="api_topup", payee=name, amount=amount, currency=result.currency, status="notified", origin="scheduler", mandate_id=proposal["mandate_id"], note="user notified")
            _action_trace(uid, name, DEFAULT_CHAR_ID)
            outcomes.append({"provider": name, "status": "low_notified"})
        else:
            outcomes.append({"provider": name, "status": "low_proposed"})
    return outcomes


async def _check_spend_monitor() -> None:
    """Compatibility entry point used by the scheduler loop."""
    await check_spend_monitor()
