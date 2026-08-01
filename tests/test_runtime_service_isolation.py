import asyncio

import pytest


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [RuntimeError("serve failed"), SystemExit(1)])
async def test_long_lived_service_failure_is_isolated(monkeypatch, error):
    import main

    seen = []
    monkeypatch.setattr("core.error_handler.log_error", lambda name, exc: seen.append((name, exc)))

    async def failing_service():
        raise error

    await main._run_long_lived_service("admin", failing_service())

    assert seen == [("runtime_service.admin", error)]


@pytest.mark.asyncio
async def test_long_lived_service_cancellation_propagates():
    import main

    async def cancelled_service():
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await main._run_long_lived_service("admin", cancelled_service())


@pytest.mark.asyncio
async def test_failed_service_does_not_cancel_sibling(monkeypatch):
    import main

    monkeypatch.setattr("core.error_handler.log_error", lambda *_args: None)
    sibling_finished = asyncio.Event()

    async def failing_service():
        raise SystemExit(1)

    async def sibling_service():
        await asyncio.sleep(0)
        sibling_finished.set()

    await asyncio.gather(
        main._run_long_lived_service("admin", failing_service()),
        main._run_long_lived_service("qq", sibling_service()),
    )

    assert sibling_finished.is_set()
