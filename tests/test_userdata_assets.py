from __future__ import annotations

import asyncio
import io
import json
import zipfile

import pytest


def _live2d_package() -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("model.model3.json", json.dumps({"FileReferences": {}}))
    return output.getvalue()


def test_authored_voice_upload_uses_logical_id_without_exposing_path(sandbox):
    from core import userdata_assets

    row = userdata_assets.store_upload(
        category="reference_audio",
        logical_id="voice_sample",
        filename="arbitrary-name.wav",
        content=b"wav",
        char_id="role_one",
        replace=True,
    )

    assert row["logical_id"] == "voice_sample"
    assert row["name"] == "voice_sample.wav"
    assert all("path" not in key for key in row)
    resolved = userdata_assets.resolve_asset_path(
        category="reference_audio", logical_id="voice_sample", char_id="role_one"
    )
    assert resolved is not None and resolved.name == "voice_sample.wav"
    with pytest.raises(ValueError):
        userdata_assets.list_assets(category="not-a-category")


def test_live2d_upload_is_backend_only_partial(sandbox):
    from core import userdata_assets

    row = userdata_assets.store_upload(
        category="live2d",
        logical_id="model_package",
        filename="source.zip",
        content=_live2d_package(),
        char_id="role_one",
        replace=True,
    )

    assert row["availability"] == "partial"
    assert row["desktop_available"] is False


def test_listing_sticker_packs_does_not_require_a_pack_filter(sandbox):
    from core import userdata_assets

    userdata_assets.store_upload(
        category="sticker_pack",
        logical_id="wave",
        filename="wave.png",
        content=b"png",
        pack="warm_pack",
        emotion="happy",
        replace=True,
    )

    row = next(
        item for item in userdata_assets.list_assets()
        if item["category"] == "sticker_pack" and item["logical_id"] == "wave"
    )
    assert row["scope"] == {"pack": "warm_pack", "emotion": "happy"}


def test_tts_preview_passes_selected_character_to_real_synthesis(monkeypatch):
    from admin.routers.settings_misc import TtsTestRequest, test_tts_config
    from core.output import voice_adapter

    captured = {}

    monkeypatch.setattr(voice_adapter, "resolve_tts_config", lambda char_id: {"char_id": char_id})
    monkeypatch.setattr(voice_adapter, "get_provider_status", lambda _cfg: {"ready": True, "provider": "gsv"})

    async def _synthesize(_text, _emotion, *, char_id=None):
        captured["char_id"] = char_id
        return b"audio"

    monkeypatch.setattr(voice_adapter, "synthesize", _synthesize)
    result = asyncio.run(test_tts_config(TtsTestRequest(text="test", char_id="role_one"), auth="test"))

    assert captured["char_id"] == "role_one"
    assert result["provider"] == "gsv"
