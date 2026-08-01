import json
import time

import pytest


class _CaptureClient:
    def __init__(self, response: str = "{}"):
        self.response = response
        self.calls = []

    async def chat(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.response


@pytest.mark.asyncio
async def test_reflect_to_episodic_routes_llm_by_frozen_character(sandbox, monkeypatch):
    from core import llm_client
    from core.memory import mid_term
    from core.memory.fixation_pipeline import reflect_to_episodic

    response = json.dumps({
        "raw_facts": ["用户提到了压力"],
        "topic_keywords": ["压力"],
        "emotion_peak": "sad",
        "emotion_texture": "沉重",
        "emotion_arc": "逐渐平静",
        "user_state": "stressed",
        "narrative_summary": "用户聊了最近的压力",
        "strength": 0.75,
    }, ensure_ascii=False)
    client = _CaptureClient(response)
    monkeypatch.setattr(llm_client, "chat", client.chat)
    uid = "background_route_reflect"
    mid_id = f"mt_{uid}_{int(time.time() * 1000)}"
    mid_term.append(
        uid,
        "用户最近有些焦虑",
        mid_id=mid_id,
        source_turn_id=f"{uid}_turn",
        char_id="character_b",
    )

    await reflect_to_episodic(uid, [mid_id], char_id="character_b")

    assert client.calls
    assert {kwargs.get("char_id") for _, kwargs in client.calls} == {"character_b"}


@pytest.mark.asyncio
async def test_identity_synthesis_routes_llm_by_frozen_character(sandbox):
    from core.memory.fixation_pipeline import _synthesize_identity

    client = _CaptureClient("{}")
    await _synthesize_identity(
        "background_route_identity",
        {},
        [{"narrative_summary": "一段经历", "strength": 0.5}],
        {},
        client,
        char_id="character_b",
    )

    assert len(client.calls) == 3
    assert {kwargs.get("char_id") for _, kwargs in client.calls} == {"character_b"}


@pytest.mark.asyncio
async def test_user_profile_llm_calls_route_by_frozen_character(sandbox, monkeypatch):
    from core import llm_client
    from core.memory import user_profile

    client = _CaptureClient("{}")
    monkeypatch.setattr(llm_client, "chat", client.chat)
    await user_profile.extract_and_update(
        "background_route_profile",
        [{"role": "user", "content": "我最近开始游泳"}],
        char_id="character_b",
    )
    client.response = "[]"
    await user_profile._compress_facts(["一条事实"], char_id="character_b")

    assert len(client.calls) == 2
    assert {kwargs.get("char_id") for _, kwargs in client.calls} == {"character_b"}


@pytest.mark.asyncio
async def test_dream_postprocessors_route_llm_by_frozen_character():
    from core.dream.distill_impression import _llm_distill
    from core.dream.dream_summary import _llm_strip_scene

    client = _CaptureClient("{}")
    await _llm_strip_scene("梦境对话", client, char_id="character_b")
    await _llm_distill("梦境对话", client, char_id="character_b")

    assert len(client.calls) == 2
    assert {kwargs.get("char_id") for _, kwargs in client.calls} == {"character_b"}
