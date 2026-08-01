import json
import sys
import time
from types import SimpleNamespace
from datetime import datetime

import pytest


def _cfg(*, enabled=True, cap=100, providers=None, payees=None):
    return {"spend": {"enabled": enabled, "daily_cap": cap, "monthly_cap": cap,
            "payee_whitelist": payees or ["deepseek"], "balance_providers": providers or []}}


def test_disabled_budget_rejects_without_ledger(sandbox, monkeypatch):
    monkeypatch.setattr("core.config_loader.get_config", lambda: _cfg(enabled=False))
    from core.actions.spend_ledger import check_budget
    assert check_budget("api_topup", "deepseek", 10) == (False, "disabled")
    assert not sandbox.spend_ledger().exists()


def test_confirmed_rows_enforce_daily_and_monthly_caps(sandbox, monkeypatch):
    monkeypatch.setattr("core.config_loader.get_config", lambda: _cfg(cap=50))
    from core.actions import spend_ledger
    assert spend_ledger.append(action="api_topup", payee="deepseek", amount=45, status="confirmed", origin="scheduler")
    assert spend_ledger.check_budget("api_topup", "deepseek", 10) == (False, "daily_cap")
    assert spend_ledger.check_budget("api_topup", "elsewhere", 1) == (False, "payee_not_whitelisted")


@pytest.mark.asyncio
async def test_low_balance_proposes_notifies_and_traces(sandbox, monkeypatch):
    import core.scheduler.triggers.spend_monitor as monitor
    provider = {"name": "deepseek", "threshold": 10, "topup_amount": 20, "topup_url": "https://pay.example"}
    monkeypatch.setattr("core.config_loader.get_config", lambda: _cfg(providers=[provider]))
    monkeypatch.setattr(monitor, "_recently_notified", lambda _p: False)
    async def balance(_p): return 2
    async def notify(_uid, _text): return True
    monkeypatch.setattr(monitor.api_balance, "fetch_balance", balance)
    monkeypatch.setattr(monitor, "_notify", notify)
    monkeypatch.setattr("core.scheduler.loop._is_ready", lambda _n: True)
    monkeypatch.setattr("core.scheduler.loop._mark", lambda _n: None)
    monkeypatch.setattr("core.scheduler.loop._owner_id", lambda: "u1")
    await monitor._check_spend_monitor()
    rows = [json.loads(x) for x in sandbox.spend_ledger().read_text(encoding="utf-8").splitlines()]
    assert [r["status"] for r in rows] == ["observed", "proposed", "notified"]


@pytest.mark.asyncio
async def test_ledger_failure_stops_before_notification(sandbox, monkeypatch):
    import core.scheduler.triggers.spend_monitor as monitor
    provider = {"name": "deepseek", "threshold": 10, "topup_amount": 20}
    monkeypatch.setattr("core.config_loader.get_config", lambda: _cfg(providers=[provider]))
    monkeypatch.setattr(monitor, "_recently_notified", lambda _p: False)
    async def balance(_p): return 2
    monkeypatch.setattr(monitor.api_balance, "fetch_balance", balance)
    monkeypatch.setattr(monitor.spend_ledger, "append", lambda **_kw: None)
    notified = False
    async def notify(*_args):
        nonlocal notified
        notified = True
        return True
    monkeypatch.setattr(monitor, "_notify", notify)
    monkeypatch.setattr("core.scheduler.loop._is_ready", lambda _n: True)
    monkeypatch.setattr("core.scheduler.loop._mark", lambda _n: None)
    monkeypatch.setattr("core.scheduler.loop._owner_id", lambda: "u1")
    await monitor._check_spend_monitor()
    assert notified is False


def test_aliyun_bss_payload_parses_both_balances_and_currency():
    from core.actions.api_balance import _parse_aliyun_bss_payload

    result = _parse_aliyun_bss_payload({
        "Success": True,
        "Data": {
            "AvailableCashAmount": "12.50",
            "AvailableAmount": "15.75",
            "Currency": "CNY",
        },
    })
    assert result is not None
    assert result.balance == 12.5
    assert result.available_cash_amount == 12.5
    assert result.available_amount == 15.75
    assert result.currency == "CNY"


def test_aliyun_bss_credentials_come_from_config(monkeypatch):
    from core.actions import api_balance

    monkeypatch.setattr(
        "core.config_loader.get_base_config",
        lambda: {
            "spend": {
                "aliyun_bss": {
                    "access_key_id": "test-access-key-id",
                    "access_key_secret": "test-access-key-secret",
                }
            }
        },
    )

    assert api_balance._load_aliyun_bss_credentials() == (
        "test-access-key-id",
        "test-access-key-secret",
    )


@pytest.mark.asyncio
async def test_aliyun_bss_query_uses_only_query_account_balance_and_keeps_secret_out_of_url(monkeypatch):
    from core.actions import api_balance

    requested_urls = []
    api_call_rows = []

    class Response:
        status = 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def json(self, **_kwargs):
            return {
                "Success": True,
                "Data": {
                    "AvailableCashAmount": "12.50",
                    "AvailableAmount": "15.75",
                    "Currency": "CNY",
                },
            }

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        def get(self, url):
            requested_urls.append(url)
            return Response()

    monkeypatch.setitem(
        sys.modules,
        "aiohttp",
        SimpleNamespace(ClientTimeout=lambda **kwargs: kwargs, ClientSession=lambda **_kwargs: Session()),
    )
    monkeypatch.setattr(api_balance, "_load_aliyun_bss_credentials", lambda: ("test-access-key-id", "test-access-key-secret"))
    monkeypatch.setattr("core.api_call_log.append", lambda **row: api_call_rows.append(row))

    result = await api_balance._fetch_aliyun_bss_balance({"kind": "aliyun_bss"})
    assert result is not None and result.balance == 12.5
    assert len(requested_urls) == 1
    assert "Action=QueryAccountBalance" in requested_urls[0]
    assert "test-access-key-secret" not in requested_urls[0]
    assert len(api_call_rows) == 1
    assert api_call_rows[0]["caller"] == "spend_monitor"
    assert api_call_rows[0]["purpose"] == "balance_check"
    assert api_call_rows[0]["provider"] == "aliyun_bss"
    assert api_call_rows[0]["model"] == "bssopenapi-2017-12-14"
    assert api_call_rows[0]["ok"] is True
    assert api_call_rows[0]["output_hint"] == "ok"
    assert "test-access-key" not in str(api_call_rows)


@pytest.mark.asyncio
async def test_aliyun_bss_http_error_returns_no_balance(monkeypatch):
    from core.actions import api_balance

    class Response:
        status = 500

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        def get(self, _url):
            return Response()

    monkeypatch.setitem(
        sys.modules,
        "aiohttp",
        SimpleNamespace(ClientTimeout=lambda **kwargs: kwargs, ClientSession=lambda **_kwargs: Session()),
    )
    monkeypatch.setattr(api_balance, "_load_aliyun_bss_credentials", lambda: ("test-access-key-id", "test-access-key-secret"))
    assert await api_balance._fetch_aliyun_bss_balance({"kind": "aliyun_bss"}) is None


@pytest.mark.asyncio
async def test_aliyun_bss_http_failure_writes_check_failed_ledger_row(sandbox, monkeypatch):
    import core.scheduler.triggers.spend_monitor as monitor

    provider = {"name": "aliyun_bss", "kind": "aliyun_bss", "threshold": 10, "topup_amount": 20}
    monkeypatch.setattr("core.config_loader.get_config", lambda: _cfg(providers=[provider], payees=["aliyun_bss"]))

    async def unavailable(_provider):
        return None

    monkeypatch.setattr(monitor.api_balance, "fetch_balance_result", unavailable)
    monkeypatch.setattr("core.scheduler.loop._is_ready", lambda _n: True)
    monkeypatch.setattr("core.scheduler.loop._mark", lambda _n: None)
    monkeypatch.setattr("core.scheduler.loop._owner_id", lambda: "u1")

    await monitor._check_spend_monitor()
    rows = [json.loads(x) for x in sandbox.spend_ledger().read_text(encoding="utf-8").splitlines()]
    assert rows[0]["action"] == "balance_check"
    assert rows[0]["status"] == "check_failed"


@pytest.mark.asyncio
async def test_aliyun_bss_healthy_balance_is_observed_in_ledger(sandbox, monkeypatch):
    import core.scheduler.triggers.spend_monitor as monitor
    from core.actions.api_balance import BalanceResult

    provider = {"name": "aliyun_bss", "kind": "aliyun_bss", "threshold": 10, "topup_amount": 20}
    monkeypatch.setattr("core.config_loader.get_config", lambda: _cfg(providers=[provider], payees=["aliyun_bss"]))

    async def balance(_provider):
        return BalanceResult(balance=12.5, currency="CNY", available_cash_amount=12.5, available_amount=15.75)

    monkeypatch.setattr(monitor.api_balance, "fetch_balance_result", balance)
    monkeypatch.setattr("core.scheduler.loop._is_ready", lambda _n: True)
    monkeypatch.setattr("core.scheduler.loop._mark", lambda _n: None)
    monkeypatch.setattr("core.scheduler.loop._owner_id", lambda: "u1")

    await monitor._check_spend_monitor()
    rows = [json.loads(x) for x in sandbox.spend_ledger().read_text(encoding="utf-8").splitlines()]
    assert [row["status"] for row in rows] == ["observed"]
    assert rows[0]["currency"] == "CNY"
    assert "available_cash_amount=12.5" in rows[0]["note"]


@pytest.mark.asyncio
async def test_manual_spend_check_requires_admin_and_returns_non_secret_outcomes(monkeypatch):
    from fastapi.testclient import TestClient
    from admin.admin_server import app

    async def check(*, force=False):
        assert force is True
        return [{"provider": "aliyun_bss", "status": "healthy"}]

    monkeypatch.setattr("core.scheduler.triggers.spend_monitor.check_spend_monitor", check)
    monkeypatch.setattr("admin.auth.get_admin_secret", lambda: "spend-test-secret")
    client = TestClient(app, raise_server_exceptions=False)

    assert client.post("/spend/check").status_code == 401
    response = client.post("/spend/check", headers={"Authorization": "Bearer spend-test-secret"})
    assert response.status_code == 200
    assert response.json() == {"outcomes": [{"provider": "aliyun_bss", "status": "healthy"}]}


def test_aliyun_bss_invalid_response_is_rejected():
    from core.actions.api_balance import _parse_aliyun_bss_payload

    assert _parse_aliyun_bss_payload({"Success": True, "Data": {"AvailableCashAmount": "3", "Currency": "CNY"}}) is None
    assert _parse_aliyun_bss_payload({"Success": False, "Data": {}}) is None


@pytest.mark.asyncio
async def test_aliyun_bss_low_balance_repeated_check_records_observations_once_per_check_but_proposes_once(sandbox, monkeypatch):
    import core.scheduler.triggers.spend_monitor as monitor
    from core.actions.api_balance import BalanceResult

    provider = {"name": "aliyun_bss", "kind": "aliyun_bss", "threshold": 10, "topup_amount": 20}
    monkeypatch.setattr("core.config_loader.get_config", lambda: _cfg(providers=[provider], payees=["aliyun_bss"]))

    async def balance(_provider):
        return BalanceResult(balance=2, currency="CNY", available_cash_amount=2, available_amount=3)

    async def notify(_uid, _text):
        return True

    monkeypatch.setattr(monitor.api_balance, "fetch_balance_result", balance)
    monkeypatch.setattr(monitor, "_notify", notify)
    monkeypatch.setattr("core.scheduler.loop._is_ready", lambda _n: True)
    monkeypatch.setattr("core.scheduler.loop._mark", lambda _n: None)
    monkeypatch.setattr("core.scheduler.loop._owner_id", lambda: "u1")

    await monitor._check_spend_monitor()
    await monitor._check_spend_monitor()

    rows = [json.loads(x) for x in sandbox.spend_ledger().read_text(encoding="utf-8").splitlines()]
    assert [row["status"] for row in rows].count("observed") == 2
    assert [row["status"] for row in rows].count("proposed") == 1
    assert [row["status"] for row in rows].count("notified") == 1
