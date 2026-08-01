"""Read-only API balance adapters. They never submit payment requests."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import math
import time
import uuid
from dataclasses import dataclass
from urllib import error as urllib_error
from urllib import request as urllib_request
from urllib.parse import quote

logger = logging.getLogger(__name__)

_ALIYUN_BSS_ENDPOINT = "https://business.aliyuncs.com/"
_ALIYUN_BSS_VERSION = "2017-12-14"
_ALIYUN_CURRENCIES = frozenset({"CNY", "USD", "JPY"})


@dataclass(frozen=True)
class BalanceResult:
    """A provider-neutral observation with only non-secret balance fields."""

    balance: float
    currency: str = "CNY"
    available_cash_amount: float | None = None
    available_amount: float | None = None


def _number(value: object) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None

def _extract_balance(payload: object) -> float | None:
    if not isinstance(payload, dict): return None
    for key in ("balance", "available_balance", "remaining", "credit"):
        try: return float(payload[key])
        except (KeyError, TypeError, ValueError): pass
    data = payload.get("data")
    return _extract_balance(data) if isinstance(data, dict) else None


def _percent_encode(value: object) -> str:
    return quote(str(value), safe="~")


def _sign_aliyun_rpc_params(params: dict[str, str], access_key_secret: str) -> str:
    canonicalized = "&".join(
        f"{_percent_encode(key)}={_percent_encode(value)}"
        for key, value in sorted(params.items())
    )
    string_to_sign = f"GET&%2F&{_percent_encode(canonicalized)}"
    digest = hmac.new(
        f"{access_key_secret}&".encode("utf-8"),
        string_to_sign.encode("utf-8"),
        hashlib.sha1,
    ).digest()
    return base64.b64encode(digest).decode("ascii")


def _load_aliyun_bss_credentials() -> tuple[str, str] | None:
    """Read the dedicated RAM key from config.yaml via the runtime loader."""
    from core.config_loader import get_base_config

    spend = get_base_config().get("spend")
    if not isinstance(spend, dict):
        return None
    block = spend.get("aliyun_bss")
    if not isinstance(block, dict):
        return None
    access_key_id = str(block.get("access_key_id") or "").strip()
    access_key_secret = str(block.get("access_key_secret") or "").strip()
    return (access_key_id, access_key_secret) if access_key_id and access_key_secret else None


def _parse_aliyun_bss_payload(payload: object, *, balance_field: str = "available_cash_amount") -> BalanceResult | None:
    if not isinstance(payload, dict) or payload.get("Success") is not True:
        return None
    data = payload.get("Data")
    if not isinstance(data, dict):
        return None
    cash = _number(data.get("AvailableCashAmount"))
    available = _number(data.get("AvailableAmount"))
    currency = str(data.get("Currency") or "").upper()
    if cash is None or available is None or currency not in _ALIYUN_CURRENCIES:
        return None
    if balance_field == "available_cash_amount":
        balance = cash
    elif balance_field == "available_amount":
        balance = available
    else:
        return None
    return BalanceResult(
        balance=balance,
        currency=currency,
        available_cash_amount=cash,
        available_amount=available,
    )


def _record_aliyun_bss_call(*, started_at: float, ok: bool, output_hint: str) -> None:
    from core.api_call_log import append

    append(
        caller="spend_monitor",
        purpose="balance_check",
        provider="aliyun_bss",
        model="bssopenapi-2017-12-14",
        duration_ms=int((time.monotonic() - started_at) * 1000),
        ok=ok,
        output_hint=output_hint,
    )


def _request_aliyun_bss_direct(url: str, timeout_s: float) -> tuple[int, object]:
    """Fetch one signed BSS RPC response without inheriting proxy settings."""
    opener = urllib_request.build_opener(urllib_request.ProxyHandler({}))
    request = urllib_request.Request(url, method="GET")
    with opener.open(request, timeout=timeout_s) as response:
        return int(response.getcode()), json.loads(response.read().decode("utf-8"))


async def _fetch_aliyun_bss_balance(provider: dict) -> BalanceResult | None:
    credentials = _load_aliyun_bss_credentials()
    if credentials is None:
        return None
    access_key_id, access_key_secret = credentials
    params = {
        "Action": "QueryAccountBalance",
        "Format": "JSON",
        "AccessKeyId": access_key_id,
        "SignatureMethod": "HMAC-SHA1",
        "Timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "SignatureNonce": uuid.uuid4().hex,
        "SignatureVersion": "1.0",
        "Version": _ALIYUN_BSS_VERSION,
    }
    params["Signature"] = _sign_aliyun_rpc_params(params, access_key_secret)
    query = "&".join(f"{_percent_encode(key)}={_percent_encode(value)}" for key, value in params.items())
    started_at = time.monotonic()
    try:
        status, payload = await asyncio.to_thread(
            _request_aliyun_bss_direct,
            _ALIYUN_BSS_ENDPOINT + "?" + query,
            float(provider.get("timeout_s", 10)),
        )
        if status >= 400:
            _record_aliyun_bss_call(started_at=started_at, ok=False, output_hint="http_error")
            return None
        result = _parse_aliyun_bss_payload(
            payload,
            balance_field=str(provider.get("balance_field") or "available_cash_amount"),
        )
        _record_aliyun_bss_call(
            started_at=started_at,
            ok=result is not None,
            output_hint="ok" if result is not None else "invalid_response",
        )
        return result
    except urllib_error.HTTPError:
        _record_aliyun_bss_call(started_at=started_at, ok=False, output_hint="http_error")
        return None
    except Exception:
        # Do not include request URLs or exceptions: either can contain credential-derived data.
        _record_aliyun_bss_call(started_at=started_at, ok=False, output_hint="request_failed")
        logger.warning("[spend] Aliyun BSS balance lookup failed")
        return None

async def fetch_balance(provider: dict) -> float | None:
    base_url = str(provider.get("base_url") or "").rstrip("/")
    if not base_url: return None
    try:
        import aiohttp
        headers = {"Authorization": f"Bearer {provider['api_key']}"} if provider.get("api_key") else {}
        timeout = aiohttp.ClientTimeout(total=float(provider.get("timeout_s", 10)))
        endpoint = str(provider.get("balance_path") or "/balance")
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(base_url + endpoint, headers=headers) as response:
                if response.status >= 400: return None
                return _extract_balance(await response.json())
    except Exception as exc:
        logger.warning("[spend] balance lookup failed provider=%s: %s", provider.get("name"), exc)
        return None


async def fetch_balance_result(provider: dict) -> BalanceResult | None:
    """Fetch one observation while retaining the legacy float adapter for other providers."""
    if str(provider.get("kind") or "").strip().lower() == "aliyun_bss":
        return await _fetch_aliyun_bss_balance(provider)
    balance = await fetch_balance(provider)
    if balance is None:
        return None
    currency = str(provider.get("currency") or "CNY").upper()
    return BalanceResult(balance=balance, currency=currency)
