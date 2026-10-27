"""W4 D4 有限重試測試（假驗證器、假時鐘、假滑鼠，不需要瀏覽器）。

執行方式（專案根目錄）：
    python -m tests.test_retry
或
    python -m pytest tests/test_retry.py -v
"""

import json

import numpy as np

from src.common.logger import AppLogger
from src.control.action_executor import PlannedClicks, RetryPolicy, execute_action
from src.control.capture import CaptureRegion
from src.control.controller import AgentController
from src.control.pipeline import EventIds, run_discard_turn
from src.control.verifier import (
    ERR_ACTION_NOT_STABLE,
    ERR_ACTION_TIMEOUT,
    ActionVerifier,
    VerifyResult,
)
from test_interface.agent_runner import SEAT, make_fake_game_state
from test_interface.fakes import FakeMouse
from tests._runner import run_module
from tests.helpers import FakeClock, make_hand_mapper

REGION = CaptureRegion(100, 50, 1920, 1200)
PLAN1 = PlannedClicks(((10, 20),), ((110, 70),))
PLAN2 = PlannedClicks(((10, 20), (30, 40)), ((110, 70), (130, 90)))


class FakeVerifier:
    """依序回傳預先指定的結果，並記錄 prepare / wait(timeout) 的呼叫。"""

    def __init__(self, results) -> None:
        self.results = list(results)
        self.prepared: list = []
        self.wait_timeouts: list = []

    def prepare(self, frame_point):
        self.prepared.append(frame_point)
        return True

    def wait(self, timeout=None):
        self.wait_timeouts.append(timeout)
        return self.results.pop(0)


def ok():
    return VerifyResult(True, True, 10.0, 3, 0.02)


def bad(code=ERR_ACTION_TIMEOUT):
    return VerifyResult(False, False, 500.0, 10, 0.0, code)


def _exec(verifier, mouse, *, plan=PLAN1, retry=RetryPolicy(), foreground=None, log_dir=None, already_done=None):
    ids = EventIds(prefix="t")
    logger = AppLogger(log_dir=str(log_dir), game_id="t") if log_dir is not None else None
    controller = AgentController(game_id="t", mouse=mouse, logger=logger)
    controller.start()
    try:
        return execute_action(
            "discard_0", 0, lambda: plan, controller,
            game_id="t", decision_id="d1", schema_action=None,
            next_event_id=ids.next, logger=logger, verifier=verifier,
            foreground_check=foreground, retry=retry, already_done=already_done,
        )
    finally:
        controller.stop()
        if logger is not None:
            logger.close()


def test_late_arrival_is_success_without_reclick():
    mouse, verifier = FakeMouse(), FakeVerifier([bad(), ok()])
    receipt, _ = _exec(verifier, mouse)

    assert mouse.clicks == [(110, 70)]  # 只點一次
    assert verifier.wait_timeouts == [None, 0.5]  # 第二次是 grace 觀察
    assert receipt.success is True and receipt.state_verified is True
    assert receipt.retry_count == 0 and receipt.error_code is None


def test_retry_after_grace_succeeds():
    mouse, verifier = FakeMouse(), FakeVerifier([bad(), bad(), ok()])
    receipt, _ = _exec(verifier, mouse)

    assert mouse.clicks == [(110, 70), (110, 70)]
    assert verifier.wait_timeouts == [None, 0.5, None]
    assert verifier.prepared == [(10, 20), (10, 20)]  # 重點前重新擷取基準幀
    assert receipt.success is True and receipt.state_verified is True
    assert receipt.retry_count == 1


def test_retry_exhausted_fails_and_records():
    mouse, verifier = FakeMouse(), FakeVerifier([bad(), bad(), bad(), bad()])
    receipt, _ = _exec(verifier, mouse)

    assert mouse.clicks == [(110, 70), (110, 70)]  # 最多重試 1 次
    assert verifier.wait_timeouts == [None, 0.5, None, 0.5]
    assert receipt.success is False and receipt.state_verified is False
    assert receipt.ui_action_executed is True
    assert receipt.retry_count == 1
    assert receipt.error_code == ERR_ACTION_TIMEOUT
    assert "已重試 1 次" in receipt.error_message
    assert receipt.should_stop is False


def test_not_stable_is_not_retried():
    mouse, verifier = FakeMouse(), FakeVerifier([bad(ERR_ACTION_NOT_STABLE)])
    receipt, _ = _exec(verifier, mouse)

    assert mouse.clicks == [(110, 70)]
    assert verifier.wait_timeouts == [None]  # 連 grace 都不用
    assert receipt.error_code == ERR_ACTION_NOT_STABLE and receipt.retry_count == 0


def test_grace_not_stable_is_not_retried():
    mouse, verifier = FakeMouse(), FakeVerifier([bad(), bad(ERR_ACTION_NOT_STABLE)])
    receipt, _ = _exec(verifier, mouse)

    assert mouse.clicks == [(110, 70)]
    assert receipt.error_code == ERR_ACTION_NOT_STABLE and receipt.retry_count == 0


def test_two_step_not_retried():
    mouse, verifier = FakeMouse(), FakeVerifier([bad()])
    receipt, _ = _exec(verifier, mouse, plan=PLAN2)

    assert mouse.clicks == [(110, 70)]  # 第一步逾時就停，不重點也不點第二步
    assert verifier.wait_timeouts == [None]
    assert receipt.should_stop is True and receipt.retry_count == 0


def test_foreground_lost_blocks_retry_click():
    calls = []

    def foreground():
        calls.append(1)
        return len(calls) <= 1  # 第一次點擊前在前景，重點前不在

    mouse, verifier = FakeMouse(), FakeVerifier([bad(), bad()])
    receipt, _ = _exec(verifier, mouse, foreground=foreground)

    assert mouse.clicks == [(110, 70)]
    assert receipt.error_code == "WINDOW_NOT_FOREGROUND"
    assert receipt.should_stop is True and receipt.retry_count == 0
    assert receipt.ui_action_executed is True


def test_no_retry_policy_keeps_old_behavior():
    mouse, verifier = FakeMouse(), FakeVerifier([bad()])
    receipt, _ = _exec(verifier, mouse, retry=None)

    assert mouse.clicks == [(110, 70)]
    assert verifier.wait_timeouts == [None]
    assert receipt.error_code == ERR_ACTION_TIMEOUT and receipt.retry_count == 0


def test_max_retries_zero_only_observes():
    mouse, verifier = FakeMouse(), FakeVerifier([bad(), bad()])
    receipt, _ = _exec(verifier, mouse, retry=RetryPolicy(max_retries=0))

    assert mouse.clicks == [(110, 70)]
    assert verifier.wait_timeouts == [None, 0.5]
    assert receipt.success is False and receipt.retry_count == 0


def test_retry_metadata_in_jsonl(tmp_path):
    _exec(FakeVerifier([bad(), bad(), ok()]), FakeMouse(), log_dir=tmp_path)

    events = [json.loads(l) for l in (tmp_path / "t.jsonl").read_text(encoding="utf-8").splitlines()]
    completed = next(e for e in events if e["event_type"] == "action_completed")

    assert completed["payload"]["retry_count"] == 1
    assert completed["metadata"]["retry"] == {"max_retries": 1, "retry_count": 1, "late_success": False}
    assert [v["phase"] for v in completed["metadata"]["verification"]] == ["initial", "grace", "retry"]


def blank(h=100, w=100):
    return np.zeros((h, w, 3), dtype=np.uint8)


def test_wait_timeout_override_and_late_change():
    base = blank()
    changed = base.copy()
    changed[10:20, 10:20] = 255
    frames = [base] * 13 + [changed] * 40
    state = {"i": 0}

    def capture():
        i = min(state["i"], len(frames) - 1)
        state["i"] += 1
        return frames[i]

    clock = FakeClock()
    verifier = ActionVerifier(
        capture, timeout=0.5, poll_interval=0.05, roi_margin=None, downsample=1,
        clock=clock, sleep=clock.sleep,
    )
    assert verifier.prepare((15, 15)) is True

    first = verifier.wait()
    assert first.error == ERR_ACTION_TIMEOUT

    late = verifier.wait(timeout=0.5)  # 沿用同一張基準幀，這次看到晚到的變化
    assert late.verified is True

    # timeout 覆寫真的有生效：0.2 秒只輪詢約 4 次
    verifier2 = ActionVerifier(
        lambda: base, timeout=5.0, poll_interval=0.05, roi_margin=None, downsample=1,
        clock=clock, sleep=clock.sleep,
    )
    verifier2.prepare((15, 15))
    short = verifier2.wait(timeout=0.2)
    assert short.error == ERR_ACTION_TIMEOUT and short.polls <= 5


def test_pipeline_discard_retry(tmp_path):
    state = make_fake_game_state("t_retry")
    mapper = make_hand_mapper(state.players[SEAT].hand)

    mouse = FakeMouse()
    blank_frame = np.zeros((1200, 1920, 3), dtype=np.uint8)
    changed_frame = blank_frame.copy()
    changed_frame[590:650, 90:170] = 255

    def capture():  # 第一次點擊沒反應，第二次（重試）才有反應
        return changed_frame if len(mouse.clicks) >= 2 else blank_frame

    clock = FakeClock()
    verifier = ActionVerifier(capture, timeout=0.5, poll_interval=0.05, clock=clock, sleep=clock.sleep)

    with AppLogger(log_dir=str(tmp_path), game_id="t_retry") as logger:
        controller = AgentController(game_id="t_retry", mouse=mouse, logger=logger)
        controller.start()
        try:
            result = run_discard_turn(
                state, SEAT, mapper, REGION, controller,
                game_id="t_retry", ids=EventIds(), logger=logger,
                verifier=verifier, retry=RetryPolicy(),
            )
        finally:
            controller.stop()

    assert mouse.clicks == [(213, 670), (213, 670)]
    assert result.success is True
    assert result.receipt.retry_count == 1 and result.receipt.state_verified is True


def test_game_state_confirms_without_waiting_or_reclick():
    mouse, verifier = FakeMouse(), FakeVerifier([bad()])
    receipt, _ = _exec(verifier, mouse, already_done=lambda: True)

    assert mouse.clicks == [(110, 70)]  # 像素沒看到變化，但遊戲已前進 -> 不重點
    assert verifier.wait_timeouts == [None]  # 連 grace 都不用等
    assert receipt.success is True and receipt.state_verified is True and receipt.retry_count == 0


def test_game_state_checked_again_before_reclick():
    answers = iter([False, True])  # 第一次問（逾時後）還沒前進；多等之後才前進
    mouse, verifier = FakeMouse(), FakeVerifier([bad(), bad()])
    receipt, _ = _exec(verifier, mouse, already_done=lambda: next(answers))

    assert mouse.clicks == [(110, 70)]
    assert receipt.success is True and receipt.retry_count == 0


def test_game_state_not_advanced_still_retries_and_errors_are_ignored():
    mouse, verifier = FakeMouse(), FakeVerifier([bad(), bad(), ok()])
    receipt, _ = _exec(verifier, mouse, already_done=lambda: False)
    assert mouse.clicks == [(110, 70), (110, 70)] and receipt.retry_count == 1

    def boom():
        raise OSError("連不到網頁")

    mouse2, verifier2 = FakeMouse(), FakeVerifier([bad(), bad(), ok()])
    receipt2, _ = _exec(verifier2, mouse2, already_done=boom)  # 確認失敗 = 不確定，走原本流程
    assert mouse2.clicks == [(110, 70), (110, 70)] and receipt2.success is True


if __name__ == "__main__":
    run_module(globals(), "test_retry")