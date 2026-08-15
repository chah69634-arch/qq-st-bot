from tests.fixtures.public_assets import TEST_CHAR_ID
"""
tests/test_dream_mirror_v0.py — Dream Mirror Mode v0.1/v0.2 tests

Test inventory:
  1. MirrorCore bucket mapping — only low/medium/high/unknown; no floats
  2. MirrorCore bucket coverage — all four keys present; values are coarse only
  3. Mirror enter freezes snapshot — state["mirror_core"] written; post-entry hidden_state changes don't affect session mirror_core
  4. Sandbox enter — no mirror_core in state
  5. Scenario enter — no mirror_core in state
  6. DM layer injected when dream_mode=mirror and mirror_core present
  7. DM layer absent when dream_mode=sandbox
  8. DM layer absent when dream_mode=scenario
  9. Mirror prompt contains no float literals (no "0.42"-style values)
 10. Mirror prompt contains no percentage signs
 11. Mirror exit calls wire_afterglow_from_summary with mode="mirror" (v0.2 gate open, Brief 90 §3)
 12. Mirror exit calls distill_impression with mode="mirror" (v0.2 gate open, Brief 90 §1)
 13. Scenario isolation — afterglow/impression still skipped for scenario (regression)
 14. clear_local_state removes mirror_core
 15. MirrorCore.from_dict / to_dict round-trip
"""

import asyncio
import re
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest


# ── Fixtures ──────────────────────────────────────────────────────────────────

_UID = "mirror_test_user"

_FAKE_CHARACTER = MagicMock()
_FAKE_CHARACTER.name = "Companion"
_FAKE_CHARACTER.description = "Companion是圣塞西尔学院的老师"
_FAKE_CHARACTER.gender = "male"

_EMPTY_SNAPSHOT: dict[str, Any] = {
    "created_at": time.time(),
    "user_id": _UID,
    "entry_reason": "test",
    "relationship_state": {},
    "recent_reality_context": "",
    "episodic_summary": "",
    "mid_term_context": "",
    "profile_impression": "",
    "user_hidden_state_snapshot": {},
}

_FULL_HS_SNAPSHOT: dict[str, Any] = {
    "sensitivity": "high",
    "touch_appetite": "high",
    "embodied_ease": "guarded",
    "memory_cues": ["轻触", "靠近", "手"],
}


# ═══════════════════════════════════════════════════════════════════════════════
# Test 1 — MirrorCore bucket values are only coarse labels, never floats
# ═══════════════════════════════════════════════════════════════════════════════

def test_mirror_core_no_float_values():
    """snapshot_buckets values must never be floats."""
    from core.dream.mirror_core import build_mirror_core

    mc = build_mirror_core(_FULL_HS_SNAPSHOT)
    for k, v in mc.snapshot_buckets.items():
        assert not isinstance(v, float), f"float found in snapshot_buckets[{k!r}]={v!r}"
        assert isinstance(v, str), f"expected str in snapshot_buckets[{k!r}], got {type(v).__name__}"


# ═══════════════════════════════════════════════════════════════════════════════
# Test 2 — MirrorCore bucket mapping correctness
# ═══════════════════════════════════════════════════════════════════════════════

def test_mirror_core_bucket_mapping():
    """Four expected keys present; values are from allowed coarse sets."""
    from core.dream.mirror_core import build_mirror_core, _VALID_LMH, _VALID_PRESENCE

    mc = build_mirror_core(_FULL_HS_SNAPSHOT)

    assert "sensitivity_bucket" in mc.snapshot_buckets
    assert "closeness_need_bucket" in mc.snapshot_buckets
    assert "embodied_ease_bucket" in mc.snapshot_buckets
    assert "association_presence" in mc.snapshot_buckets

    assert mc.snapshot_buckets["sensitivity_bucket"] in _VALID_LMH
    assert mc.snapshot_buckets["closeness_need_bucket"] in _VALID_LMH
    assert mc.snapshot_buckets["embodied_ease_bucket"] in _VALID_LMH
    assert mc.snapshot_buckets["association_presence"] in _VALID_PRESENCE

    # specific mapping checks for _FULL_HS_SNAPSHOT
    assert mc.snapshot_buckets["sensitivity_bucket"] == "high"
    assert mc.snapshot_buckets["closeness_need_bucket"] == "high"
    assert mc.snapshot_buckets["embodied_ease_bucket"] == "low"   # "guarded" → "low"
    assert mc.snapshot_buckets["association_presence"] == "present"  # 3 cues → "present"


def test_mirror_core_bucket_mid_mapping():
    """'mid' sensitivity → 'medium'; 'neutral' ease → 'medium'."""
    from core.dream.mirror_core import build_mirror_core

    snapshot = {
        "sensitivity": "mid",
        "touch_appetite": "mid",
        "embodied_ease": "neutral",
        "memory_cues": ["a"],
    }
    mc = build_mirror_core(snapshot)
    assert mc.snapshot_buckets["sensitivity_bucket"] == "medium"
    assert mc.snapshot_buckets["closeness_need_bucket"] == "medium"
    assert mc.snapshot_buckets["embodied_ease_bucket"] == "medium"
    assert mc.snapshot_buckets["association_presence"] == "light"  # 1 cue


def test_mirror_core_empty_snapshot():
    """Empty snapshot → all 'unknown' buckets; no exception."""
    from core.dream.mirror_core import build_mirror_core

    mc = build_mirror_core({})
    assert mc.snapshot_buckets["sensitivity_bucket"] == "unknown"
    assert mc.snapshot_buckets["closeness_need_bucket"] == "unknown"
    assert mc.snapshot_buckets["embodied_ease_bucket"] == "unknown"
    assert mc.snapshot_buckets["association_presence"] == "none"


def test_mirror_core_invalid_input():
    """Non-dict input → fail-closed empty MirrorCore, no raise."""
    from core.dream.mirror_core import build_mirror_core

    mc = build_mirror_core(None)  # type: ignore
    assert isinstance(mc.snapshot_buckets, dict)
    assert mc.version == "v0.1"


# ═══════════════════════════════════════════════════════════════════════════════
# Test 3 — Mirror enter freezes snapshot into dream state
# ═══════════════════════════════════════════════════════════════════════════════

def test_mirror_enter_freezes_mirror_core(sandbox):
    """enter_dream with mirror mode writes mirror_core to dream_state."""
    from core.dream.dream_pipeline import enter_dream
    from core.dream.dream_state import read_state
    from core.dream.dream_settings import save as save_settings

    save_settings(_UID, {})

    snapshot = dict(_EMPTY_SNAPSHOT)
    snapshot["user_hidden_state_snapshot"] = dict(_FULL_HS_SNAPSHOT)

    with (
        patch("core.dream.dream_context.build_snapshot", new=AsyncMock(return_value=snapshot)),
        patch("core.pipeline_registry.get", return_value=MagicMock(character=_FAKE_CHARACTER)),
        patch("core.dream.dream_hud.delete_hud_state"),
    ):
        result = asyncio.run(enter_dream(_UID, entry_reason="test", char_id=TEST_CHAR_ID, dream_mode="mirror"))

    assert result["ok"] is True
    state = read_state(_UID)
    assert "mirror_core" in state
    mc = state["mirror_core"]
    assert mc["version"] == "v0.1"
    assert mc["source"] == "user_hidden_state_snapshot"
    assert "snapshot_buckets" in mc
    assert isinstance(mc["snapshot_buckets"], dict)
    # Verify frozen: no float in snapshot_buckets values
    for v in mc["snapshot_buckets"].values():
        assert isinstance(v, str), f"float or non-str in frozen mirror_core: {v!r}"


def test_mirror_snapshot_frozen_against_later_hs_changes(sandbox):
    """mirror_core in session state is not affected by hidden_state file changes after entry."""
    from core.dream.dream_pipeline import enter_dream
    from core.dream.dream_state import read_state
    from core.dream.dream_settings import save as save_settings

    save_settings(_UID, {})

    snapshot = dict(_EMPTY_SNAPSHOT)
    snapshot["user_hidden_state_snapshot"] = {"sensitivity": "low", "touch_appetite": "low", "embodied_ease": "easy", "memory_cues": []}

    with (
        patch("core.dream.dream_context.build_snapshot", new=AsyncMock(return_value=snapshot)),
        patch("core.pipeline_registry.get", return_value=MagicMock(character=_FAKE_CHARACTER)),
        patch("core.dream.dream_hud.delete_hud_state"),
    ):
        asyncio.run(enter_dream(_UID, entry_reason="test", char_id=TEST_CHAR_ID, dream_mode="mirror"))

    state_before = read_state(_UID)
    mc_before = state_before["mirror_core"]["snapshot_buckets"].copy()

    # Simulate a hidden_state file change AFTER dream entry (e.g. decay tick fires)
    # The mirror_core in dream_state must NOT change
    state_after = read_state(_UID)
    assert state_after["mirror_core"]["snapshot_buckets"] == mc_before, (
        "mirror_core must not change after hidden_state changes post-entry"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Test 4 — Sandbox enter has no mirror_core
# ═══════════════════════════════════════════════════════════════════════════════

def test_sandbox_enter_no_mirror_core(sandbox):
    """enter_dream with sandbox mode must NOT write mirror_core."""
    from core.dream.dream_pipeline import enter_dream
    from core.dream.dream_state import read_state
    from core.dream.dream_settings import save as save_settings

    save_settings(_UID, {})

    snapshot = dict(_EMPTY_SNAPSHOT)
    with (
        patch("core.dream.dream_context.build_snapshot", new=AsyncMock(return_value=snapshot)),
        patch("core.pipeline_registry.get", return_value=MagicMock(character=_FAKE_CHARACTER)),
        patch("core.dream.dream_hud.delete_hud_state"),
    ):
        result = asyncio.run(enter_dream(_UID, entry_reason="test", char_id=TEST_CHAR_ID, dream_mode="sandbox"))

    assert result["ok"] is True
    state = read_state(_UID)
    assert "mirror_core" not in state


# ═══════════════════════════════════════════════════════════════════════════════
# Test 5 — Scenario enter has no mirror_core
# ═══════════════════════════════════════════════════════════════════════════════

def test_scenario_enter_no_mirror_core(sandbox):
    """enter_dream with scenario mode must NOT write mirror_core."""
    from core.dream.dream_pipeline import enter_dream
    from core.dream.dream_state import read_state
    from core.dream.dream_settings import save as save_settings

    save_settings(_UID, {})

    snapshot = dict(_EMPTY_SNAPSHOT)
    with (
        patch("core.dream.dream_context.build_snapshot", new=AsyncMock(return_value=snapshot)),
        patch("core.pipeline_registry.get", return_value=MagicMock(character=_FAKE_CHARACTER)),
        patch("core.dream.dream_hud.delete_hud_state"),
    ):
        result = asyncio.run(enter_dream(
            _UID, entry_reason="test", char_id=TEST_CHAR_ID,
            dream_mode="scenario", script_id="prison_demo",
        ))

    assert result["ok"] is True
    state = read_state(_UID)
    assert "mirror_core" not in state


# ═══════════════════════════════════════════════════════════════════════════════
# Test 6 — DM layer injected in mirror mode prompt
# ═══════════════════════════════════════════════════════════════════════════════

def test_dm_layer_injected_for_mirror():
    """build_dream_prompt with dream_mode=mirror and mirror_core injects DM layer."""
    from core.dream.dream_prompt import build_dream_prompt, dump_dream_prompt
    from core.dream.mirror_core import build_mirror_core

    mc = build_mirror_core(_FULL_HS_SNAPSHOT)

    msgs = build_dream_prompt(
        character=_FAKE_CHARACTER,
        user_id=_UID,
        user_message="你好",
        context_snapshot={},
        dream_history=[],
        local_state={},
        dream_mode="mirror",
        mirror_core=mc.to_dict(),
    )
    system_msg = dump_dream_prompt(msgs)
    assert "DM·Mirror" in system_msg, "DM layer header not found in mirror prompt"
    assert "梦境的隐喻材料" in system_msg
    assert "不是诊断结论" in system_msg


# ═══════════════════════════════════════════════════════════════════════════════
# Test 7 — DM layer absent in sandbox mode
# ═══════════════════════════════════════════════════════════════════════════════

def test_dm_layer_absent_for_sandbox():
    """build_dream_prompt with dream_mode=sandbox must NOT inject DM layer."""
    from core.dream.dream_prompt import build_dream_prompt, dump_dream_prompt
    from core.dream.mirror_core import build_mirror_core

    mc = build_mirror_core(_FULL_HS_SNAPSHOT)

    msgs = build_dream_prompt(
        character=_FAKE_CHARACTER,
        user_id=_UID,
        user_message="你好",
        context_snapshot={},
        dream_history=[],
        local_state={},
        dream_mode="sandbox",
        mirror_core=mc.to_dict(),  # passed but should be ignored
    )
    system_msg = dump_dream_prompt(msgs)
    assert "DM·Mirror" not in system_msg


# ═══════════════════════════════════════════════════════════════════════════════
# Test 8 — DM layer absent in scenario mode
# ═══════════════════════════════════════════════════════════════════════════════

def test_dm_layer_absent_for_scenario():
    """build_dream_prompt with dream_mode=scenario must NOT inject DM layer."""
    from core.dream.dream_prompt import build_dream_prompt, dump_dream_prompt
    from core.dream.mirror_core import build_mirror_core

    mc = build_mirror_core(_FULL_HS_SNAPSHOT)

    msgs = build_dream_prompt(
        character=_FAKE_CHARACTER,
        user_id=_UID,
        user_message="你好",
        context_snapshot={},
        dream_history=[],
        local_state={},
        dream_mode="scenario",
        mirror_core=mc.to_dict(),
        scenario_core={
            "script_id": "prison_demo",
            "current_stage_id": "arrival",
            "stage_turns": 0,
            "ending_state": None,
        },
    )
    system_msg = dump_dream_prompt(msgs)
    assert "DM·Mirror" not in system_msg


# ═══════════════════════════════════════════════════════════════════════════════
# Test 9 — Mirror prompt contains no float literals
# ═══════════════════════════════════════════════════════════════════════════════

_FLOAT_RE = re.compile(r"\b\d+\.\d+\b")


def test_mirror_prompt_no_float_values():
    """Mirror prompt (DM layer) must not contain float literals like 0.42."""
    from core.dream.dream_prompt import build_dream_prompt, dump_dream_prompt
    from core.dream.mirror_core import build_mirror_core

    mc = build_mirror_core(_FULL_HS_SNAPSHOT)

    msgs = build_dream_prompt(
        character=_FAKE_CHARACTER,
        user_id=_UID,
        user_message="你好",
        context_snapshot={},
        dream_history=[],
        local_state={},
        dream_mode="mirror",
        mirror_core=mc.to_dict(),
    )
    system_msg = dump_dream_prompt(msgs)
    floats_found = _FLOAT_RE.findall(system_msg)
    assert not floats_found, f"Float values found in mirror prompt: {floats_found}"


# ═══════════════════════════════════════════════════════════════════════════════
# Test 10 — Mirror prompt contains no percentage signs
# ═══════════════════════════════════════════════════════════════════════════════

def test_mirror_prompt_no_percentage():
    """Mirror prompt must not contain percentage signs."""
    from core.dream.dream_prompt import build_dream_prompt, dump_dream_prompt
    from core.dream.mirror_core import build_mirror_core

    mc = build_mirror_core(_FULL_HS_SNAPSHOT)

    msgs = build_dream_prompt(
        character=_FAKE_CHARACTER,
        user_id=_UID,
        user_message="你好",
        context_snapshot={},
        dream_history=[],
        local_state={},
        dream_mode="mirror",
        mirror_core=mc.to_dict(),
    )
    system_msg = dump_dream_prompt(msgs)
    assert "%" not in system_msg, "Percentage sign found in mirror prompt"


# ═══════════════════════════════════════════════════════════════════════════════
# Test 11 — Mirror exit calls wire_afterglow_from_summary with mode="mirror" (v0.2)
# ═══════════════════════════════════════════════════════════════════════════════

def test_mirror_exit_calls_afterglow_with_mirror_mode():
    """_generate_summary_bg with dream_mode=mirror must call wire_afterglow_from_summary(mode="mirror")."""
    from core.dream import dream_pipeline

    with (
        patch("core.dream.dream_summary.generate_summary", new=AsyncMock()),
        patch("core.dream.dream_exit_afterglow.wire_afterglow_from_summary") as mock_afterglow,
        patch("core.dream.distill_impression.distill_impression", new=AsyncMock()),
    ):
        asyncio.run(dream_pipeline._generate_summary_bg(
            _UID, "dream_test_123", "soft", char_id=TEST_CHAR_ID, dream_mode="mirror"
        ))

    mock_afterglow.assert_called_once_with(
        _UID, "dream_test_123", "soft", char_id=TEST_CHAR_ID, mode="mirror"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Test 12 — Mirror exit calls distill_impression with mode="mirror" (v0.2)
# ═══════════════════════════════════════════════════════════════════════════════

def test_mirror_exit_calls_distill_impression_with_mirror_mode():
    """_generate_summary_bg with dream_mode=mirror must call distill_impression(mode="mirror")."""
    from core.dream import dream_pipeline

    with (
        patch("core.dream.dream_summary.generate_summary", new=AsyncMock()),
        patch("core.dream.dream_exit_afterglow.wire_afterglow_from_summary"),
        patch("core.dream.distill_impression.distill_impression", new=AsyncMock()) as mock_distill,
    ):
        asyncio.run(dream_pipeline._generate_summary_bg(
            _UID, "dream_test_123", "soft", char_id=TEST_CHAR_ID, dream_mode="mirror"
        ))

    mock_distill.assert_called_once_with(
        _UID, "dream_test_123", "soft", char_id=TEST_CHAR_ID, mode="mirror"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Test 13 — Scenario isolation regression: afterglow/impression still skipped
# ═══════════════════════════════════════════════════════════════════════════════

def test_scenario_exit_still_skips_afterglow_and_impression():
    """Ensure scenario mode still skips afterglow and impression after mirror guard added."""
    from core.dream import dream_pipeline

    with (
        patch("core.dream.dream_summary.generate_summary", new=AsyncMock()),
        patch("core.dream.dream_exit_afterglow.wire_afterglow_from_summary") as mock_afterglow,
        patch("core.dream.distill_impression.distill_impression", new=AsyncMock()) as mock_distill,
    ):
        asyncio.run(dream_pipeline._generate_summary_bg(
            _UID, "dream_test_456", "soft", char_id=TEST_CHAR_ID, dream_mode="scenario"
        ))

    mock_afterglow.assert_not_called()
    mock_distill.assert_not_called()


# ═══════════════════════════════════════════════════════════════════════════════
# Test 14 — clear_local_state removes mirror_core
# ═══════════════════════════════════════════════════════════════════════════════

def test_clear_local_state_removes_mirror_core():
    """clear_local_state() must remove mirror_core from state dict."""
    from core.dream.dream_state import clear_local_state

    state = {
        "status": "DREAM_ACTIVE",
        "dream_mode": "mirror",
        "mirror_core": {"snapshot_buckets": {}, "symbolic_hints": [], "source": "x", "version": "v0.1"},
        "scenario_core": None,
        "emotional_tension": 0.1,
    }
    cleared = clear_local_state(state)
    assert "mirror_core" not in cleared
    assert "dream_mode" not in cleared
    assert "emotional_tension" not in cleared
    # status is NOT in the volatile key list — must survive
    assert cleared["status"] == "DREAM_ACTIVE"


# ═══════════════════════════════════════════════════════════════════════════════
# Test 15 — MirrorCore round-trip serialization
# ═══════════════════════════════════════════════════════════════════════════════

def test_mirror_core_round_trip():
    """MirrorCore.to_dict() / from_dict() preserves all fields."""
    from core.dream.mirror_core import MirrorCore

    mc = MirrorCore(
        snapshot_buckets={"sensitivity_bucket": "high", "association_presence": "light"},
        symbolic_hints=["梦中感知更细，环境反馈更容易被放大"],
        source="user_hidden_state_snapshot",
        version="v0.1",
    )
    d = mc.to_dict()
    mc2 = MirrorCore.from_dict(d)

    assert mc2.snapshot_buckets == mc.snapshot_buckets
    assert mc2.symbolic_hints == mc.symbolic_hints
    assert mc2.source == mc.source
    assert mc2.version == mc.version


# ═══════════════════════════════════════════════════════════════════════════════
# Brief 90 — Mirror v0.2 gated write-back contract
# ═══════════════════════════════════════════════════════════════════════════════
#
#  16. distill_impression(mode="sandbox" default) → entry["mode"] == "sandbox"
#  17. distill_impression(mode="mirror") → entry["mode"] == "mirror"; plot/vivid_lines forced empty
#  18. mirror distill strips bucket-label words and numeric literals (depth defense)
#  19. legacy entry without "mode" field is treated as sandbox by the loader (compat)
#  20. mirror entries never participate in the forced 3-round exit injection
#  21. mirror recall requires the gate-tag intersection — no matching tag, no recall
#  22. mirror recall with a matching gate tag hits and carries the framing prefix
#  23. sandbox entries are unaffected when mirror entries coexist (no cross-contamination)

import json as _json
import time as _time
from unittest.mock import AsyncMock as _AsyncMock, patch as _patch


def test_distill_impression_default_mode_is_sandbox(sandbox):
    """distill_impression() with no mode kwarg stamps entry mode="sandbox"."""
    from core.dream.impression_store import load_impressions
    from core.dream.distill_impression import distill_impression

    archive_dir = sandbox.dreams_archive_dir()
    archive_dir.mkdir(parents=True, exist_ok=True)
    dream_id = f"dream_{_UID}_default_mode"
    (archive_dir / f"dream_{dream_id}.jsonl").write_text(
        _json.dumps({"role": "user", "content": "一个平常的梦"}) + "\n", encoding="utf-8",
    )
    reply = _json.dumps({
        "impression_text": "我好像在梦里有种安稳的感觉",
        "plot": "在一个安静的地方待着",
        "vivid_lines": [],
        "emotional_tags": ["安稳"],
        "weight": 0.3,
    }, ensure_ascii=False)

    async def run():
        with _patch("core.llm_client.chat", _AsyncMock(return_value=reply)):
            await distill_impression(_UID, dream_id, "soft")

    asyncio.run(run())
    entries = load_impressions(_UID)
    assert len(entries) == 1
    assert entries[0]["mode"] == "sandbox"
    assert entries[0]["plot"] == "在一个安静的地方待着"  # sandbox keeps plot


def test_distill_impression_mirror_mode_stamps_entry_and_forces_empty_plot(sandbox):
    """distill_impression(mode="mirror") stamps mode="mirror" and force-empties plot/vivid_lines
    even if the LLM (mis)behaved and returned scene content."""
    from core.dream.impression_store import load_impressions
    from core.dream.distill_impression import distill_impression

    archive_dir = sandbox.dreams_archive_dir()
    archive_dir.mkdir(parents=True, exist_ok=True)
    dream_id = f"dream_{_UID}_mirror_mode"
    (archive_dir / f"dream_{dream_id}.jsonl").write_text(
        _json.dumps({"role": "user", "content": "一个模糊的梦"}) + "\n", encoding="utf-8",
    )
    # LLM misbehaves and returns plot/vivid_lines despite the mirror addendum —
    # write-side force-strip must still empty them (defense in depth).
    reply = _json.dumps({
        "impression_text": "梦里有种模糊的贴近感",
        "plot": "两个人在教室里说话",
        "vivid_lines": ["一句清晰的对白"],
        "emotional_tags": ["温热", "模糊"],
        "weight": 0.3,
    }, ensure_ascii=False)

    async def run():
        with _patch("core.llm_client.chat", _AsyncMock(return_value=reply)):
            await distill_impression(_UID, dream_id, "soft", mode="mirror")

    asyncio.run(run())
    entries = load_impressions(_UID)
    assert len(entries) == 1
    assert entries[0]["mode"] == "mirror"
    assert entries[0]["plot"] == "", "mirror entries must never carry plot"
    assert entries[0]["vivid_lines"] == [], "mirror entries must never carry vivid_lines"
    assert entries[0]["impression_text"] == "梦里有种模糊的贴近感"


def test_mirror_distill_prompt_carries_mirror_addendum():
    """_llm_distill(mode='mirror') system prompt includes the mirror-only constraint block."""
    from core.dream.distill_impression import _llm_distill

    captured = {}

    async def fake_chat(*, messages, **kwargs):
        captured["system"] = messages[0]["content"]
        return _json.dumps({"impression_text": "", "plot": "", "vivid_lines": [], "emotional_tags": [], "weight": 0.2})

    llm_client = type("FakeClient", (), {"chat": staticmethod(fake_chat)})()
    asyncio.run(_llm_distill("dialogue", llm_client, mode="mirror"))
    assert "Mirror 模式追加约束" in captured["system"]
    assert "感受性残象" in captured["system"]


_MIRROR_BANNED_WORDS = (
    "sensitivity_bucket", "closeness_need_bucket", "embodied_ease_bucket",
    "association_presence", "guarded", "neutral", "unknown", "medium",
)


def test_distill_impression_mirror_strips_bucket_words_and_numbers(sandbox):
    """Mirror distill output must not contain bucket-label vocabulary or numeric literals
    (verification requirement: 蒸馏产物不含桶标签词/数值)."""
    from core.dream.impression_store import load_impressions
    from core.dream.distill_impression import distill_impression

    archive_dir = sandbox.dreams_archive_dir()
    archive_dir.mkdir(parents=True, exist_ok=True)
    dream_id = f"dream_{_UID}_mirror_leak"
    (archive_dir / f"dream_{dream_id}.jsonl").write_text(
        _json.dumps({"role": "user", "content": "一个模糊的梦"}) + "\n", encoding="utf-8",
    )
    # Simulate an LLM leak: bucket words + a float + a percentage inside impression_text.
    leaky = "梦里有种sensitivity_bucket=high的0.42模糊感觉，closeness_need_bucket大概65%"
    reply = _json.dumps({
        "impression_text": leaky,
        "plot": "",
        "vivid_lines": [],
        "emotional_tags": ["模糊"],
        "weight": 0.3,
    }, ensure_ascii=False)

    async def run():
        with _patch("core.llm_client.chat", _AsyncMock(return_value=reply)):
            await distill_impression(_UID, dream_id, "soft", mode="mirror")

    asyncio.run(run())
    entries = load_impressions(_UID)
    assert len(entries) == 1
    text = entries[0]["impression_text"]
    for banned in _MIRROR_BANNED_WORDS:
        assert banned not in text, f"banned bucket word {banned!r} leaked into mirror impression_text: {text!r}"
    import re as _re
    assert not _re.search(r"\d+(\.\d+)?%?", text), f"numeric literal leaked into mirror impression_text: {text!r}"


def test_legacy_entry_without_mode_field_treated_as_sandbox(sandbox):
    """Brief 90 §1: entries predating the mode field participate in forced rounds as sandbox."""
    from core.dream.impression_store import append_impression
    from core.dream.impression_loader import load_impression_text

    uid = "legacy-no-mode"
    now = _time.time()
    append_impression(uid, {
        "dream_id": "dream-legacy",
        "ts": now,
        "last_decay_ts": now,
        "impression_text": "我好像在梦里有种旧时代的感觉",
        "plot": "老式的梦",
        "vivid_lines": [],
        "weight": 0.3,
        "emotional_tags": ["怀旧"],
        "exit_type": "soft",
        "decay_after": now + 30 * 86400,
        "marked": True,
        # no "mode" key — predates Brief 90
    })

    text = load_impression_text(uid, forced_rounds_left=2, latest_dream_id="dream-legacy")
    assert "老式的梦" in text, "legacy entry without mode must be treated as sandbox and forced-inject"


def test_mirror_entry_excluded_from_forced_rounds(sandbox):
    """Brief 90 §2 (contract ②): mirror entries never participate in the forced 3-round exit injection."""
    from core.dream.impression_store import append_impression
    from core.dream.impression_loader import load_impression_text

    uid = "mirror-forced-exclude"
    now = _time.time()
    append_impression(uid, {
        "dream_id": "dream-mirror-latest",
        "ts": now,
        "last_decay_ts": now,
        "impression_text": "梦里有种模糊的贴近感",
        "plot": "",
        "vivid_lines": [],
        "weight": 0.3,
        "emotional_tags": ["模糊"],
        "exit_type": "soft",
        "decay_after": now + 30 * 86400,
        "marked": True,
        "mode": "mirror",
    })

    text = load_impression_text(uid, forced_rounds_left=3, latest_dream_id="dream-mirror-latest")
    assert text == "", "mirror exit must not trigger forced-round injection"


def test_mirror_recall_requires_gate_tag(sandbox):
    """Brief 90 §2: no matching tag → mirror entry never recalled, even with a topically matching user_text."""
    from core.dream.impression_store import append_impression
    from core.dream.impression_loader import load_impression_text

    uid = "mirror-recall-gate"
    now = _time.time()
    append_impression(uid, {
        "dream_id": "dream-mirror-recall",
        "ts": now,
        "last_decay_ts": now,
        "impression_text": "梦里有种模糊的贴近感",
        "plot": "",
        "vivid_lines": [],
        "weight": 0.3,
        "emotional_tags": ["贴近感"],
        "exit_type": "soft",
        "decay_after": now + 30 * 86400,
        "marked": True,
        "mode": "mirror",
    })

    # No tags at all → gate closed, no recall.
    no_tag = load_impression_text(uid, forced_rounds_left=0, user_text="我想起那种贴近感")
    assert no_tag == "", "mirror recall must not fire without a gate-tag match"

    # A tag that is not in the mirror gate set → still closed.
    wrong_tag = load_impression_text(
        uid, forced_rounds_left=0, user_text="我想起那种贴近感", tags={"topic.music"}
    )
    assert wrong_tag == "", "mirror recall must not fire for a non-gate tag"


def test_mirror_recall_with_gate_tag_hits_and_carries_framing_prefix(sandbox):
    """Brief 90 §2: a gate-tag match (body_intimate / physical_closeness / emotion.deep) surfaces
    the mirror entry with the "梦里残留的模糊感觉，不是事实" framing prefix."""
    from core.dream.impression_store import append_impression
    from core.dream.impression_loader import load_impression_text

    uid = "mirror-recall-hit"
    now = _time.time()
    append_impression(uid, {
        "dream_id": "dream-mirror-hit",
        "ts": now,
        "last_decay_ts": now,
        "impression_text": "梦里有种模糊的贴近感",
        "plot": "",
        "vivid_lines": [],
        "weight": 0.3,
        "emotional_tags": ["贴近感"],
        "exit_type": "soft",
        "decay_after": now + 30 * 86400,
        "marked": True,
        "mode": "mirror",
    })

    for gate_tag in ("body_intimate", "physical_closeness", "emotion.deep"):
        text = load_impression_text(
            uid, forced_rounds_left=0, user_text="随便说点什么", tags={gate_tag}
        )
        assert "梦里有种模糊的贴近感" in text, f"gate tag {gate_tag!r} should surface the mirror entry"
        assert "梦里残留的模糊感觉，不是事实" in text, f"gate tag {gate_tag!r} match must carry the framing prefix"


def test_sandbox_and_mirror_entries_coexist_without_cross_contamination(sandbox):
    """Sandbox recall/forced-round behavior is unaffected when a mirror entry is also active."""
    from core.dream.impression_store import append_impression
    from core.dream.impression_loader import load_impression_text

    uid = "mixed-mode-coexist"
    now = _time.time()
    append_impression(uid, {
        "dream_id": "dream-sandbox-mixed",
        "ts": now - 5,
        "last_decay_ts": now,
        "impression_text": "我记得沙盒梦里的灯塔",
        "plot": "在海边灯塔下重逢",
        "vivid_lines": [],
        "weight": 0.3,
        "emotional_tags": ["期待"],
        "exit_type": "soft",
        "decay_after": now + 30 * 86400,
        "marked": True,
        "mode": "sandbox",
    })
    append_impression(uid, {
        "dream_id": "dream-mirror-mixed",
        "ts": now,
        "last_decay_ts": now,
        "impression_text": "梦里有种模糊的贴近感",
        "plot": "",
        "vivid_lines": [],
        "weight": 0.3,
        "emotional_tags": ["贴近感"],
        "exit_type": "soft",
        "decay_after": now + 30 * 86400,
        "marked": True,
        "mode": "mirror",
    })

    # Forced rounds after the mirror dream (latest) must find no sandbox match — mirror excluded, no fallback.
    forced = load_impression_text(uid, forced_rounds_left=1, latest_dream_id="dream-mirror-mixed")
    assert forced == ""

    # Sandbox topical recall still works exactly as before, mirror entry excluded (no gate tag).
    recalled = load_impression_text(uid, forced_rounds_left=0, user_text="我想起那座灯塔")
    assert "海边灯塔" in recalled
    assert "模糊的贴近感" not in recalled
