"""Focused regression coverage for Activity P0 persistence and turn ownership."""
from __future__ import annotations
from tests.fixtures.public_assets import TEST_CHAR_ID

import pytest

from admin.routers.reading import _persist_new_session
from core.activity import activity_store
from core.activity import chess
from core.activity import gomoku
from core.activity import store
from core.activity.reading_session import ReadingSession, new_session_id, now_iso


def _reading_session(uid: str, *, char_id: str = TEST_CHAR_ID) -> ReadingSession:
    now = now_iso()
    return ReadingSession(
        session_id=new_session_id(), uid=uid, char_id=char_id,
        file_id="book", filename="book.pdf", total_pages=2, current_page=1,
        created_at=now, updated_at=now, status="active",
    )


def test_chess_human_turns_remain_unrestricted() -> None:
    state = chess.make_initial_state(opponent="human")
    assert chess.apply_move(chess.apply_move(state, "e2e4"), "e7e5")["turn"] == "white"


def test_chess_rejects_regular_move_on_pending_or_ai_turn() -> None:
    state = chess.make_initial_state(opponent="character_ai")
    pending = chess.apply_move(state, "e2e4")
    assert pending["pending_ai_turn"] is True
    with pytest.raises(ValueError, match="AI 回合.*ai_move"):
        chess.apply_move(pending, "e7e5")

    pending["pending_ai_turn"] = False
    with pytest.raises(ValueError, match="AI 回合.*ai_move"):
        chess.apply_move(pending, "e7e5")
    assert chess.apply_ai_move(chess.apply_move(state, "e2e4"))["pending_ai_turn"] is False


def test_gomoku_rejects_regular_move_on_pending_or_ai_turn(sandbox) -> None:
    session = gomoku.start_game("user1", TEST_CHAR_ID, opponent="character_ai", ai_response_mode="pending")
    gomoku.make_move(session.uid, session.char_id, session.session_id, 7, 7)
    with pytest.raises(ValueError, match="AI 回合.*ai_move"):
        gomoku.make_move(session.uid, session.char_id, session.session_id, 6, 6)

    assert gomoku.apply_ai_move(session.uid, session.char_id, session.session_id)["pending_ai_turn"] is False

    state = session.state
    state["current_turn"] = "white"
    state["pending_ai_turn"] = False
    store.update_state(session.char_id, session.uid, "gomoku", session.session_id, state)
    with pytest.raises(ValueError, match="AI 回合.*ai_move"):
        gomoku.make_move(session.uid, session.char_id, session.session_id, 6, 6)


def test_generic_store_write_failures_do_not_return_success(sandbox, monkeypatch) -> None:
    session = store.create_session("user1", TEST_CHAR_ID, "gomoku")
    monkeypatch.setattr(store, "safe_write_json", lambda *_args, **_kwargs: False)
    with pytest.raises(store.ActivityPersistenceError):
        store.update_state(TEST_CHAR_ID, "user1", "gomoku", session.session_id, {"moves": [1]})
    with pytest.raises(store.ActivityPersistenceError):
        store.close_session(TEST_CHAR_ID, "user1", "gomoku", session.session_id)


def test_generic_store_does_not_close_old_session_before_failed_replacement(sandbox, monkeypatch) -> None:
    old = store.create_session("user1", TEST_CHAR_ID, "chess")
    monkeypatch.setattr(store, "safe_write_json", lambda *_args, **_kwargs: False)
    with pytest.raises(store.ActivityPersistenceError):
        store.create_session("user1", TEST_CHAR_ID, "chess")
    assert store.load_session(TEST_CHAR_ID, "user1", "chess", old.session_id).status == "active"


def test_reading_store_failures_are_not_silent(sandbox, monkeypatch) -> None:
    session = _reading_session("user1")
    monkeypatch.setattr(activity_store, "safe_write_json", lambda *_args, **_kwargs: False)
    with pytest.raises(store.ActivityPersistenceError):
        activity_store.save_session(session)

    monkeypatch.setattr(activity_store, "safe_write_json", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(activity_store, "safe_write_text", lambda *_args, **_kwargs: False)
    with pytest.raises(store.ActivityPersistenceError):
        activity_store.save_pages(session.char_id, session.uid, session.session_id, ["one", "two"])


def test_reading_new_session_cleanup_and_old_active_protection(sandbox, monkeypatch) -> None:
    old = _reading_session("user1")
    activity_store.save_session(old)
    activity_store.save_pages(old.char_id, old.uid, old.session_id, ["old one", "old two"])
    replacement = _reading_session("user1")

    monkeypatch.setattr(activity_store, "safe_write_json", lambda *_args, **_kwargs: False)
    with pytest.raises(store.ActivityPersistenceError):
        _persist_new_session(replacement, ["new one", "new two"])
    assert activity_store.load_session(old.char_id, old.uid, old.session_id).status == "active"


def test_reading_exact_uid_loading_never_scans_other_users(sandbox) -> None:
    first = _reading_session("user-a")
    second = _reading_session("user-b")
    second.session_id = first.session_id
    activity_store.save_session(first)
    activity_store.save_session(second)
    assert activity_store.load_session(TEST_CHAR_ID, "user-a", first.session_id).uid == "user-a"
    assert activity_store.load_session(TEST_CHAR_ID, "user-b", first.session_id).uid == "user-b"
    assert activity_store.load_session(TEST_CHAR_ID, "other-user", first.session_id) is None
