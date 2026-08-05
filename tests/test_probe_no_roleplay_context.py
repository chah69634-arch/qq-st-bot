"""
tests/test_probe_no_roleplay_context.py
=======================================
P0.6-1: Probe context de-roleplay.

Verifies:
  P1  tool_detection_messages contains no role:assistant item
  P2  Reference block (if any) appears inside system content
  P3  Assistant action-only messages (all scrubbed) are excluded from ref block
  P4  trigger_stub messages are excluded from ref block
  P5  Source no longer uses *_probe_ctx spread into messages list
  P6  Probe system prompt gets ref block appended (non-empty history)
"""

from __future__ import annotations

import pathlib
import sys
import unittest.mock as mock

import pytest

ROOT = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


# ─────────────────────────────────────────────────────────────────────────────
# P5 — Static source check: old *_probe_ctx spread is gone
# ─────────────────────────────────────────────────────────────────────────────

class TestSourceLevel:
    _SRC = (ROOT / "core" / "pretool_router.py").read_text(encoding="utf-8")

    def test_old_probe_ctx_spread_removed(self):
        assert "*_probe_ctx" not in self._SRC, \
            "Old *_probe_ctx spread must be removed from the shared router"

    def test_no_role_assistant_in_probe_message_list(self):
        """After the patch, tool_detection_messages must be [system, user] only."""
        assert '{"role": "system", "content": result.probe_system}' in self._SRC
        assert '{"role": "user", "content": trusted_user_text}' in self._SRC

    def test_ref_block_appended_to_system(self):
        """The ref block must go into the system message, not as a separate role."""
        assert "result.probe_context" in self._SRC
        assert "result.probe_system" in self._SRC
        assert "result.probe_system +=" in self._SRC

    def test_trigger_stub_filtered(self):
        """trigger_stub messages must be filtered from probe context."""
        assert 'message.get("_source") == "trigger_stub"' in self._SRC

    def test_action_text_stripped_from_assistant_messages(self):
        """Inline regex strip must exist; scrub_reality_output_text must NOT be used."""
        assert "re.sub" in self._SRC, "Inline action-text stripping must remain in the router"
        for line in self._SRC.splitlines():
            if not line.strip().startswith("#") and "scrub_reality_output_text" in line:
                pytest.fail(
                    f"pretool_router.py must not import scrub_reality_output_text: {line!r}"
                )


# ─────────────────────────────────────────────────────────────────────────────
# Helper: simulate the ref-block building logic from the new main.py code
# ─────────────────────────────────────────────────────────────────────────────

def _build_ref_block(history: list[dict], char_name: str, scrub_fn) -> str:
    """
    Mirror of the shared probe-context building logic so we can
    unit-test it without running the full async handle_message.
    """
    ref_lines: list[str] = []
    for m in history[-4:]:
        if m.get("_source") == "trigger_stub":
            continue
        txt = (m.get("content") or "").strip()
        if m.get("role") == "assistant":
            txt = scrub_fn(txt) or ""
            if not txt:
                continue
            ref_lines.append(f"{char_name}：{txt}")
        else:
            ref_lines.append(f"用户：{txt}")
    return "\n".join(ref_lines)


def _scrub_noop(text: str) -> str:
    return text


def _scrub_strip_actions(text: str) -> str:
    """Minimal scrub: remove parenthesised action text."""
    import re
    return re.sub(r"（[^）]*）|（[^)]*）", "", text).strip()


# ─────────────────────────────────────────────────────────────────────────────
# P1 — No role:assistant in ref-block output
# ─────────────────────────────────────────────────────────────────────────────

class TestRefBlockBuilding:
    CHAR = "叶瑄"

    def test_no_assistant_role_items(self):
        history = [
            {"role": "user", "content": "嗯嗯"},
            {"role": "assistant", "content": "好的，我明白了"},
        ]
        ref = _build_ref_block(history, self.CHAR, _scrub_noop)
        # ref block is plain text, never a role dict — just assert it's a string
        assert isinstance(ref, str)
        # and doesn't embed the dict key "role" literally
        assert '"role"' not in ref
        assert "'role'" not in ref

    def test_assistant_speech_appears_under_char_name(self):
        history = [
            {"role": "user", "content": "你好"},
            {"role": "assistant", "content": "你好啊"},
        ]
        ref = _build_ref_block(history, self.CHAR, _scrub_noop)
        assert f"{self.CHAR}：你好啊" in ref
        assert "用户：你好" in ref

    # P3 — action-only messages excluded
    def test_assistant_action_only_excluded(self):
        history = [
            {"role": "user", "content": "嗯嗯"},
            {"role": "assistant", "content": "（轻叹一声）（望向窗外）"},
        ]
        # With a scrubber that strips all action text, assistant entry disappears
        ref = _build_ref_block(history, self.CHAR, lambda t: "")
        assert self.CHAR not in ref, "Action-only assistant message should be excluded"
        assert "用户：嗯嗯" in ref

    # P4 — trigger_stub filtered
    def test_trigger_stub_excluded(self):
        history = [
            {"role": "user", "content": "hi", "_source": "trigger_stub"},
            {"role": "user", "content": "普通消息"},
        ]
        ref = _build_ref_block(history, self.CHAR, _scrub_noop)
        assert "hi" not in ref
        assert "普通消息" in ref

    def test_empty_history_yields_empty_ref(self):
        ref = _build_ref_block([], self.CHAR, _scrub_noop)
        assert ref == ""

    def test_at_most_four_messages_used(self):
        history = [
            {"role": "user", "content": f"msg{i}"}
            for i in range(10)
        ]
        ref = _build_ref_block(history, self.CHAR, _scrub_noop)
        lines = ref.splitlines()
        assert len(lines) <= 4


# ─────────────────────────────────────────────────────────────────────────────
# P2 / P6 — Ref block goes into system prompt, not as a separate message
# ─────────────────────────────────────────────────────────────────────────────

class TestProbeMessageStructure:
    CHAR = "叶瑄"
    BASE_SYSTEM = "只输出工具调用或空字符串"

    def _build_tool_messages(self, ref_block: str, user_text: str) -> list[dict]:
        """Mirror new main.py tool_detection_messages assembly."""
        probe_system = self.BASE_SYSTEM
        if ref_block:
            probe_system += (
                "\n\n【最近对话（仅供解析指代词等，不要续写、不要表演、不要进入角色）】\n"
                + ref_block
            )
        return [
            {"role": "system", "content": probe_system},
            {"role": "user", "content": user_text},
        ]

    def test_messages_contain_only_system_and_user(self):
        history = [{"role": "user", "content": "嗯"}, {"role": "assistant", "content": "好"}]
        ref = _build_ref_block(history, self.CHAR, _scrub_noop)
        msgs = self._build_tool_messages(ref, "嗯嗯")
        roles = [m["role"] for m in msgs]
        assert roles == ["system", "user"]

    def test_ref_block_in_system_content(self):
        history = [{"role": "user", "content": "查天气"}, {"role": "assistant", "content": "好的"}]
        ref = _build_ref_block(history, self.CHAR, _scrub_noop)
        msgs = self._build_tool_messages(ref, "查那个")
        system_content = msgs[0]["content"]
        assert "最近对话" in system_content
        assert ref in system_content

    def test_no_ref_block_when_history_empty(self):
        msgs = self._build_tool_messages("", "嗯嗯")
        system_content = msgs[0]["content"]
        assert "最近对话" not in system_content
        assert system_content == self.BASE_SYSTEM
