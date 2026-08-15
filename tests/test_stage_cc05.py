"""CC-05: peer_reply arbiter bonus + AI chain continuation tests."""
from __future__ import annotations
from tests.fixtures.public_assets import TEST_CHAR_ID, TEST_PEER_CHAR_ID, TEST_THIRD_CHAR_ID

import uuid

import pytest


def _settings(**overrides):
    from core.stage.models import StageSettings

    values = {
        "min_responders": 1,
        "max_responders": 2,
        "max_ai_chain_depth": 3,
        "respond_threshold": 0.5,
        "spontaneous_threshold": 0.7,
        "transcript_limit": 200,
        "talkativeness": {TEST_CHAR_ID: 0.5, TEST_PEER_CHAR_ID: 0.5},
        # Brief 85 §4 topic-seed is orthogonal to what these tests exercise and
        # uses real random.random() when unmocked — pin it off for determinism.
        "topic_seed_prob": 0.0,
    }
    values.update(overrides)
    return StageSettings(**values)


def _stage(roster=(TEST_CHAR_ID, TEST_PEER_CHAR_ID), **setting_overrides):
    from core.stage.store import create_stage

    group_id = f"cc05-{uuid.uuid4().hex[:8]}"
    return create_stage(group_id, "owner", list(roster), settings=_settings(**setting_overrides))


def _entry(speaker_id, content="hi", ts=1.0, turn_id="t", triggered_by="user"):
    from core.stage.models import TranscriptEntry

    return TranscriptEntry(speaker_id, content, ts, turn_id, triggered_by)


# ── default defaults ──────────────────────────────────────────────────────────

def test_max_ai_chain_depth_default_is_3():
    from core.stage.models import StageSettings

    assert StageSettings().max_ai_chain_depth == 3


def test_max_ai_chain_depth_from_dict_default_is_3():
    from core.stage.models import StageSettings

    assert StageSettings.from_dict({}).max_ai_chain_depth == 3


# ── PEER_REPLY_BASE is exported ───────────────────────────────────────────────

def test_peer_reply_base_constant_exists():
    from core.stage.arbiter import PEER_REPLY_BASE

    assert 0.0 < PEER_REPLY_BASE <= 1.0


# ── arbiter: peer_reply term ──────────────────────────────────────────────────

def test_peer_reply_bonus_when_peer_spoke(sandbox):
    """peer_reply > 0 when a non-owner AI char just spoke; score clears Phase B chain threshold."""
    from core.stage.arbiter import score_candidates

    stage = _stage()
    transcript = [
        _entry("owner", "hello", ts=1),
        _entry(TEST_CHAR_ID, "something", ts=2),  # peer spoke last
    ]
    ranked = score_candidates(stage, transcript, candidates=[TEST_PEER_CHAR_ID])
    score = ranked[0]

    assert score.parts["peer_reply"] > 0.0
    # Phase B chain threshold is respond_threshold * 0.8; score must clear it.
    assert score.total > stage.settings.respond_threshold * 0.8


def test_peer_reply_zero_when_owner_spoke(sandbox):
    """No peer_reply bonus when the owner sent the latest message."""
    from core.stage.arbiter import score_candidates

    stage = _stage()
    transcript = [_entry("owner", "hello")]
    ranked = score_candidates(stage, transcript, candidates=[TEST_PEER_CHAR_ID])

    assert ranked[0].parts["peer_reply"] == 0.0


def test_peer_reply_zero_when_self_spoke_last(sandbox):
    """Candidate does not get peer_reply bonus when they themselves spoke last."""
    from core.stage.arbiter import score_candidates

    stage = _stage()
    transcript = [
        _entry("owner", "hello", ts=1),
        _entry(TEST_PEER_CHAR_ID, "I just spoke", ts=2),
    ]
    ranked = score_candidates(stage, transcript, candidates=[TEST_PEER_CHAR_ID])

    assert ranked[0].parts["peer_reply"] == 0.0


def test_peer_reply_empty_transcript_has_no_bonus(sandbox):
    """Empty transcript is treated as owner-spoke; no peer_reply bonus."""
    from core.stage.arbiter import score_candidates

    stage = _stage()
    ranked = score_candidates(stage, [], candidates=[TEST_PEER_CHAR_ID])

    assert ranked[0].parts["peer_reply"] == 0.0


def test_addressed_still_outweighs_peer_reply_for_ranking(sandbox):
    """addressed (0.9) still dominates: the addressed char ranks first even when both get peer_reply."""
    from core.character_name_provider import get_char_name
    from core.stage.arbiter import score_candidates

    stage = _stage()
    name = get_char_name(TEST_CHAR_ID)
    # yexuanJ-5412 spoke last and directly addressed yexuan
    transcript = [_entry(TEST_PEER_CHAR_ID, f"@{name} 你觉得呢？", ts=1)]
    ranked = score_candidates(stage, transcript)

    assert ranked[0].char_id == TEST_CHAR_ID
    assert ranked[0].parts["addressed"] == 0.9
    # yexuanJ-5412 gets peer_reply but not addressed — should rank lower
    other = next(s for s in ranked if s.char_id == TEST_PEER_CHAR_ID)
    assert other.parts["peer_reply"] == 0.0  # self-spoke, no bonus


def test_peer_reply_scales_with_talkativeness(sandbox):
    """Talkative char gets a larger peer_reply bonus than a quieter one."""
    from core.stage.arbiter import score_candidates
    from core.stage.store import create_stage
    from core.stage.models import StageSettings

    settings = StageSettings(talkativeness={TEST_CHAR_ID: 1.0, TEST_PEER_CHAR_ID: 0.2})
    stage = create_stage(f"cc05-talk-{uuid.uuid4().hex[:6]}", "owner", [TEST_CHAR_ID, TEST_PEER_CHAR_ID], settings=settings)

    # yexuan spoke → yexuanJ-5412 (quiet) gets peer_reply
    ranked_quiet = score_candidates(stage, [_entry(TEST_CHAR_ID, "hi")], candidates=[TEST_PEER_CHAR_ID])
    # yexuanJ-5412 spoke → yexuan (talkative) gets peer_reply
    ranked_talk = score_candidates(stage, [_entry(TEST_PEER_CHAR_ID, "hi")], candidates=[TEST_CHAR_ID])

    assert ranked_talk[0].parts["peer_reply"] > ranked_quiet[0].parts["peer_reply"]


def test_recency_penalty_still_reduces_peer_reply_benefit(sandbox):
    """recency_penalty for a char who just spoke reduces their total even with peer_reply from third speaker."""
    from core.stage.arbiter import score_candidates
    from core.stage.models import StageSettings
    from core.stage.store import create_stage

    # Three-char roster: yexuan, yexuanJ-5412, hongcha. yexuanJ-5412 spoke twice recently.
    settings = StageSettings(talkativeness={TEST_CHAR_ID: 0.5, TEST_PEER_CHAR_ID: 0.5, TEST_THIRD_CHAR_ID: 0.5})
    stage = create_stage(
        f"cc05-recency-{uuid.uuid4().hex[:6]}",
        "owner",
        [TEST_CHAR_ID, TEST_PEER_CHAR_ID, TEST_THIRD_CHAR_ID],
        settings=settings,
    )
    transcript = [
        _entry(TEST_CHAR_ID, "msg1", ts=1),
        _entry(TEST_PEER_CHAR_ID, "msg2", ts=2),
        _entry(TEST_PEER_CHAR_ID, "msg3", ts=3),  # spoke twice — high recency
        _entry(TEST_THIRD_CHAR_ID, "msg4", ts=4),  # peer for both yexuan and yexuanJ-5412
    ]
    ranked = score_candidates(stage, transcript, candidates=[TEST_CHAR_ID, TEST_PEER_CHAR_ID])
    yexuan_score = next(s for s in ranked if s.char_id == TEST_CHAR_ID)
    heavy_score = next(s for s in ranked if s.char_id == TEST_PEER_CHAR_ID)

    # yexuan: peer_reply applies, modest recency (1 occurrence) → higher total
    # yexuanJ-5412: peer_reply applies but heavy recency penalty (2 occurrences) → lower
    assert yexuan_score.total > heavy_score.total


# ── Phase B chain: continues when peer spoke, bounded by max depth ─────────────

@pytest.mark.asyncio
async def test_phase_b_chain_continues_when_peer_spoke(sandbox):
    """Phase B continues when peer_reply pushes score above respond_threshold*0.8."""
    from core.stage.runner import run_owner_turn
    from core.stage.store import create_stage

    # Default talkativeness=0.5 for both chars.
    # With only owner speaking: base = 0.25 < threshold (0.5*0.8=0.4) → chain breaks.
    # With peer speaking: base + peer_reply = 0.25 + 0.20 = 0.45 > 0.40 → chain continues.
    settings = _settings(max_responders=1, max_ai_chain_depth=3, allow_silent_rounds=False)
    stage = create_stage(f"cc05-chain-{uuid.uuid4().hex[:6]}", "owner", [TEST_CHAR_ID, TEST_PEER_CHAR_ID], settings=settings)

    async def generate(stage, speaker_id, transcript, turn_id, triggered_by):
        return "我先说说窗外的雨。" if speaker_id == TEST_CHAR_ID else "我更想谈谈刚才那部电影。"

    result = await run_owner_turn(
        stage.group_id,
        "开始",
        generate_reply=generate,
        turn_id="t-chain",
    )

    # Phase A: one char replies to owner.
    # Phase B: the other char gets peer_reply bonus and replies, chain advances.
    assert result.ai_chain_depth >= 1
    assert len(result.replies) >= 2  # Phase A + at least one Phase B reply


@pytest.mark.asyncio
async def test_phase_b_chain_bounded_at_max_depth(sandbox):
    """ai_chain_depth never exceeds max_ai_chain_depth regardless of peer scores."""
    from core.stage.runner import run_owner_turn
    from core.stage.store import create_stage

    max_depth = 2
    settings = _settings(
        max_responders=1,
        max_ai_chain_depth=max_depth,
        talkativeness={TEST_CHAR_ID: 1.0, TEST_PEER_CHAR_ID: 1.0},
    )
    stage = create_stage(f"cc05-bound-{uuid.uuid4().hex[:6]}", "owner", [TEST_CHAR_ID, TEST_PEER_CHAR_ID], settings=settings)

    async def generate(stage, speaker_id, transcript, turn_id, triggered_by):
        return f"{speaker_id}-says"

    result = await run_owner_turn(stage.group_id, "go", generate_reply=generate, turn_id="t-bound")

    assert result.ai_chain_depth <= max_depth


@pytest.mark.asyncio
async def test_phase_b_no_chain_when_roster_has_only_one_char(sandbox):
    """Phase B cannot advance when there is only one AI char (nobody else to respond)."""
    from core.stage.runner import run_owner_turn
    from core.stage.store import create_stage

    settings = _settings(
        max_responders=1,
        max_ai_chain_depth=3,
        talkativeness={TEST_CHAR_ID: 1.0},
    )
    stage = create_stage(f"cc05-solo-{uuid.uuid4().hex[:6]}", "owner", [TEST_CHAR_ID], settings=settings)

    async def generate(stage, speaker_id, transcript, turn_id, triggered_by):
        return "solo-reply"

    result = await run_owner_turn(stage.group_id, "hello", generate_reply=generate, turn_id="t-solo")

    # yexuan spoke last → no other candidates in Phase B → depth stays 0
    assert result.ai_chain_depth == 0
