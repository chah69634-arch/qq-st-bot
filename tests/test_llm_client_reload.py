from __future__ import annotations

from types import SimpleNamespace

import pytest


class _FakeClient:
    def __init__(self, *, fail: bool = False):
        self.fail = fail
        self.close_calls = 0

    async def close(self):
        self.close_calls += 1
        if self.fail:
            raise RuntimeError("close failed")


@pytest.mark.asyncio
async def test_reload_closes_model_and_vision_clients(monkeypatch):
    from core import llm_client, model_registry

    model_client = _FakeClient()
    vision_client = _FakeClient()
    monkeypatch.setattr(
        model_registry,
        "_model_clients",
        {"chat": SimpleNamespace(client=model_client)},
    )
    monkeypatch.setattr(llm_client, "_vision_client", vision_client)

    await llm_client.reload_client()

    assert model_client.close_calls == 1
    assert vision_client.close_calls == 1
    assert model_registry._model_clients == {}
    assert llm_client._vision_client is None


@pytest.mark.asyncio
async def test_reload_deduplicates_clients_and_contains_close_failure(monkeypatch, caplog):
    from core import llm_client, model_registry

    shared_client = _FakeClient(fail=True)
    healthy_client = _FakeClient()
    monkeypatch.setattr(
        model_registry,
        "_model_clients",
        {
            "first": SimpleNamespace(client=shared_client),
            "duplicate": SimpleNamespace(client=shared_client),
            "healthy": SimpleNamespace(client=healthy_client),
        },
    )
    monkeypatch.setattr(llm_client, "_vision_client", shared_client)

    with caplog.at_level("WARNING"):
        await llm_client.reload_client()

    assert shared_client.close_calls == 1
    assert healthy_client.close_calls == 1
    assert "关闭旧客户端失败" in caplog.text
