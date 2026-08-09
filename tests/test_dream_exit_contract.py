"""Dream exit machine contract regression tests."""
from __future__ import annotations

from core.dream.exit_contract import (
    COMPLETION_COMPLETE,
    COMPLETION_INTERRUPTED,
    CONTROL_ABSENT,
    CONTROL_INVALID,
    CONTROL_ACCEPTED,
    DREAM_CONTROL_ACCEPT,
    EXIT_MECHANISM_USER_HARD_EXIT,
    completion_for_exit,
    parse_dream_control,
)


def test_accept_control_is_stripped_before_visible_output():
    parsed = parse_dream_control(
        "我会在这里等你。\n<dream_control>{\"exit\":\"accept\"}</dream_control>"
    )
    assert parsed.visible_reply == "我会在这里等你。"
    assert parsed.decision == DREAM_CONTROL_ACCEPT
    assert parsed.status == CONTROL_ACCEPTED


def test_missing_control_does_not_infer_acceptance_from_narrative():
    parsed = parse_dream_control("好，我们回到现实吧。")
    assert parsed.visible_reply == "好，我们回到现实吧。"
    assert parsed.decision is None
    assert parsed.status == CONTROL_ABSENT


def test_invalid_control_is_stripped_but_cannot_close():
    parsed = parse_dream_control("仍有余韵\n<dream_control>accept</dream_control>")
    assert parsed.visible_reply == "仍有余韵"
    assert parsed.decision is None
    assert parsed.status == CONTROL_INVALID


def test_long_user_hard_exit_can_be_complete_but_short_exit_is_interrupted():
    assert completion_for_exit(EXIT_MECHANISM_USER_HARD_EXIT, 5) == COMPLETION_COMPLETE
    assert completion_for_exit(EXIT_MECHANISM_USER_HARD_EXIT, 4) == COMPLETION_INTERRUPTED
