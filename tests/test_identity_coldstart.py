from tests.fixtures.public_assets import TEST_CHAR_ID
"""
tests/test_identity_coldstart.py

Brief 104 §3 · identity-2 冷启动量化 + 降级体验：
1. event_log.count_real_turns() 统计 full_log.md 里 speaker:user 的行数（lifetime，
   不受 short_term 20 轮滑窗 / event_log 按天分片影响）。
2. prompt_builder.build() 新增 identity_coldstart 参数：user_identity_text 为空且
   identity_coldstart=True 时注入 6a_user_identity_coldstart 层；user_identity_text
   非空时仍走原有 6a_user_identity 层，两者互斥。
3. consolidate_to_identity() 检测到用户首次出现 confidence>=0.5 的维度时，记一条
   identity_coldstart 日志到 fixation.jsonl；此前已达标则不重复记。
"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

from core.memory import event_log


# ─────────────────────────────────────────────────────────────────────────────
# 1. event_log.count_real_turns()
# ─────────────────────────────────────────────────────────────────────────────

_UID = "test_identity_coldstart_uid"


def test_count_real_turns_zero_when_no_log(sandbox):
    assert event_log.count_real_turns(_UID) == 0


def test_count_real_turns_counts_user_lines_only(sandbox):
    for i in range(3):
        event_log.append(_UID, "user", f"消息{i}", turn_id=f"t{i}")
        event_log.append(_UID, "assistant", f"回复{i}", turn_id=f"t{i}")
    assert event_log.count_real_turns(_UID) == 3


def test_count_real_turns_unaffected_by_day_file_deletion(sandbox):
    event_log.append(_UID, "user", "只有一条", turn_id="only1")
    event_log.append(_UID, "assistant", "回复", turn_id="only1")
    from datetime import datetime
    today = datetime.now().strftime("%Y-%m-%d")
    event_log.delete_day(_UID, today)
    # full_log.md 永不随按天文件删除而变化
    assert event_log.count_real_turns(_UID) == 1


# ─────────────────────────────────────────────────────────────────────────────
# 2. prompt_builder 6a_user_identity_coldstart 层
# ─────────────────────────────────────────────────────────────────────────────

def _character():
    char = MagicMock()
    char.name = "Companion"
    char.system_prompt = ""
    char.description = ""
    char.personality = ""
    char.scenario = ""
    char.mes_example = ""
    char.jailbreak_entries = []
    return char


def _build(user_identity_text: str, identity_coldstart: bool) -> list[dict]:
    from core import prompt_builder

    with (
        patch("core.prompt_builder._load_jailbreak", return_value=""),
        patch("core.prompt_builder._load_style_hint", return_value=""),
        patch("core.presence.get_last_seen_text", return_value=""),
        patch("core.author_note_rotator.get_current_note", return_value=""),
        patch("core.config_loader.get_config", return_value={"chat": {"style": "roleplay"}}),
        patch("core.mood_text.get_mood_text", return_value=""),
        patch("core.activity_manager.get_prompt_fragment", return_value=""),
    ):
        messages, _ = prompt_builder.build(
            character=_character(), user_id="identity-coldstart-test", user_message="你好",
            history=[], relation={"role": "朋友"}, profile={}, group_context=[],
            user_identity_text=user_identity_text,
            identity_coldstart=identity_coldstart,
        )
    return messages


def test_coldstart_layer_injected_when_identity_empty_and_flag_true():
    messages = _build("", True)
    layers = [m.get("_layer") for m in messages]
    assert "6a_user_identity_coldstart" in layers
    assert "6a_user_identity" not in layers


def test_coldstart_layer_absent_when_flag_false():
    messages = _build("", False)
    layers = [m.get("_layer") for m in messages]
    assert "6a_user_identity_coldstart" not in layers
    assert "6a_user_identity" not in layers


def test_real_identity_text_takes_priority_over_coldstart_flag():
    messages = _build("- 信任建立较慢，需要反复确认", True)
    layers = [m.get("_layer") for m in messages]
    assert "6a_user_identity" in layers
    assert "6a_user_identity_coldstart" not in layers


def test_coldstart_layer_has_no_drop_priority():
    messages = _build("", True)
    layer = next(m for m in messages if m.get("_layer") == "6a_user_identity_coldstart")
    assert "_drop_priority" not in layer


# ─────────────────────────────────────────────────────────────────────────────
# 3. consolidate_to_identity() 首个有效维度观测日志
# ─────────────────────────────────────────────────────────────────────────────

_UID_PREFIX = "identity_coldstart_consolidate"


def _seed_episode(uid, char_id, ep_id="ep1"):
    from core.memory import episodic_memory as em
    em._save_memories(uid, [{
        "id": ep_id,
        "narrative_summary": "聊到了最近的工作",
        "emotion_peak": "neutral",
        "strength": 0.8,
        "consolidated_at": None,
        "timestamp": 0.0,
    }], char_id=char_id)


def _identity_llm_response(confidence: float, evidence_count: int) -> str:
    return json.dumps({
        "trust_pattern": {
            "text": "她信任建立较快", "confidence": confidence,
            "evidence_count": evidence_count, "counter_evidence_count": 0,
        },
    }, ensure_ascii=False)


def _read_fixation_records():
    from core.sandbox import get_paths
    path = get_paths().fixation_log()
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def test_consolidate_logs_first_valid_identity_dimension(sandbox):
    from core.memory.fixation_pipeline import consolidate_to_identity

    uid = f"{_UID_PREFIX}_first_valid"
    char_id = TEST_CHAR_ID
    _seed_episode(uid, char_id)
    for i in range(3):
        event_log.append(uid, "user", f"消息{i}", char_id=char_id, turn_id=f"ic_{i}")
        event_log.append(uid, "assistant", f"回复{i}", char_id=char_id, turn_id=f"ic_{i}")

    llm = MagicMock()
    # confidence 0.7 * evidence_factor 1.0 * maturity_factor 1.0 (ev=10) = 0.7 >= 0.5
    llm.chat = AsyncMock(return_value=_identity_llm_response(confidence=0.7, evidence_count=10))

    result = asyncio.run(consolidate_to_identity(uid, llm, char_id=char_id))
    assert result is True

    coldstart = [
        r for r in _read_fixation_records()
        if r.get("job") == "identity_coldstart" and r.get("uid") == uid
    ]
    assert len(coldstart) == 1
    assert coldstart[0]["real_turns"] == 3
    assert coldstart[0]["dimensions"] == ["trust_pattern"]


def test_consolidate_low_confidence_does_not_log_coldstart(sandbox):
    from core.memory.fixation_pipeline import consolidate_to_identity

    uid = f"{_UID_PREFIX}_low_conf"
    char_id = TEST_CHAR_ID
    _seed_episode(uid, char_id)

    llm = MagicMock()
    # confidence 0.3 * 1.0 * 1.0 = 0.3 < 0.5 门槛，不应记录
    llm.chat = AsyncMock(return_value=_identity_llm_response(confidence=0.3, evidence_count=10))

    result = asyncio.run(consolidate_to_identity(uid, llm, char_id=char_id))
    assert result is True

    coldstart = [
        r for r in _read_fixation_records()
        if r.get("job") == "identity_coldstart" and r.get("uid") == uid
    ]
    assert coldstart == []


def test_consolidate_does_not_relog_once_already_valid(sandbox):
    from core.memory.fixation_pipeline import consolidate_to_identity

    uid = f"{_UID_PREFIX}_already_valid"
    char_id = TEST_CHAR_ID
    _seed_episode(uid, char_id, ep_id="ep1")

    llm = MagicMock()
    llm.chat = AsyncMock(return_value=_identity_llm_response(confidence=0.7, evidence_count=10))
    asyncio.run(consolidate_to_identity(uid, llm, char_id=char_id))

    # 第二轮固化：再喂一条新 episode，dimension 已经 valid，不应重复记录
    _seed_episode(uid, char_id, ep_id="ep2")
    asyncio.run(consolidate_to_identity(uid, llm, char_id=char_id))

    coldstart = [
        r for r in _read_fixation_records()
        if r.get("job") == "identity_coldstart" and r.get("uid") == uid
    ]
    assert len(coldstart) == 1


# ─────────────────────────────────────────────────────────────────────────────
# 4. 观测端点 GET /memory/fixation/status, /memory/fixation/identity-coldstart-summary
# ─────────────────────────────────────────────────────────────────────────────

def test_fixation_status_endpoint_includes_coldstart_record(sandbox, monkeypatch):
    from admin.routers import memory as memory_router
    from core.memory.fixation_pipeline import consolidate_to_identity

    uid = f"{_UID_PREFIX}_endpoint"
    char_id = TEST_CHAR_ID
    monkeypatch.setattr(memory_router, "_resolve_char_id", lambda cid: char_id)
    _seed_episode(uid, char_id)

    llm = MagicMock()
    llm.chat = AsyncMock(return_value=_identity_llm_response(confidence=0.7, evidence_count=10))
    asyncio.run(consolidate_to_identity(uid, llm, char_id=char_id))

    result = asyncio.run(memory_router.get_fixation_status(uid, char_id=char_id, auth="dummy"))

    assert result["uid"] == uid
    assert len(result["identity_coldstart"]) == 1
    assert result["identity_coldstart"][0]["dimensions"] == ["trust_pattern"]


def test_identity_coldstart_summary_endpoint_aggregates_samples(sandbox):
    from admin.routers import memory as memory_router
    from core.memory.fixation_pipeline import consolidate_to_identity

    char_id = TEST_CHAR_ID
    llm = MagicMock()
    llm.chat = AsyncMock(return_value=_identity_llm_response(confidence=0.7, evidence_count=10))

    for i in range(2):
        uid = f"{_UID_PREFIX}_summary_{i}"
        _seed_episode(uid, char_id)
        for _ in range(i + 1):
            event_log.append(uid, "user", "hi", char_id=char_id)
            event_log.append(uid, "assistant", "hi back", char_id=char_id)
        asyncio.run(consolidate_to_identity(uid, llm, char_id=char_id))

    result = asyncio.run(memory_router.get_identity_coldstart_summary(auth="dummy"))

    assert result["summary"]["sample_count"] >= 2
    assert result["summary"]["avg_real_turns"] is not None
