import time

from core.phone_control import task_state


def test_start_and_record_step_increments(sandbox):
    task_state.start_task("t1", "owner", "把购物车下单到支付页")
    step, reason = task_state.record_step("t1")
    assert step == 1
    assert reason is None
    step2, reason2 = task_state.record_step("t1")
    assert step2 == 2
    assert reason2 is None


def test_record_step_unknown_task(sandbox):
    step, reason = task_state.record_step("does-not-exist")
    assert step is None
    assert reason == "unknown_task"


def test_record_step_max_steps_exceeded(sandbox):
    task_state.start_task("t2", "owner", "任务")
    for _ in range(task_state.MAX_STEPS):
        step, reason = task_state.record_step("t2")
        assert reason is None
    step, reason = task_state.record_step("t2")
    assert step is None
    assert reason == "max_steps_exceeded"
    # 标记 refused 之后再调用应该幂等地拒绝，不会再往下计数
    step2, reason2 = task_state.record_step("t2")
    assert step2 is None
    assert reason2 == "task_already_refused"


def test_record_step_timeout(sandbox, monkeypatch):
    task_state.start_task("t3", "owner", "任务")

    real_time = time.time
    monkeypatch.setattr(task_state.time, "time", lambda: real_time() + task_state.STEP_TIMEOUT_SECONDS + 1)
    step, reason = task_state.record_step("t3")
    assert step is None
    assert reason == "step_timeout"


def test_mark_status_terminal(sandbox):
    task_state.start_task("t4", "owner", "任务")
    task_state.mark_status("t4", "done")
    step, reason = task_state.record_step("t4")
    assert step is None
    assert reason == "task_already_done"


def test_mark_status_rejects_non_terminal():
    import pytest

    with pytest.raises(ValueError):
        task_state.mark_status("whatever", "active")
