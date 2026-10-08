"""W4 D3 點擊後畫面驗證測試（合成畫面 + 假時鐘，不需要瀏覽器）。

執行方式（專案根目錄）：
    python -m tests.test_verifier
或
    python -m pytest tests/test_verifier.py -v
"""

import json
import tempfile
from pathlib import Path

import numpy as np

from src.common.logger import AppLogger
from src.control.action_executor import PlannedClicks, execute_action
from src.control.capture import CaptureRegion
from src.control.controller import AgentController
from src.control.pipeline import EventIds, run_discard_turn
from src.control.tile_mapper import TileBox, TileMapper
from src.control.verifier import (
    ERR_ACTION_NOT_STABLE,
    ERR_ACTION_TIMEOUT,
    ERR_CAPTURE_FAILED,
    ERR_FRAME_SIZE_CHANGED,
    ActionVerifier,
    VerifyResult,
    frame_diff_ratio,
)
from test_interface.agent_runner import SEAT, make_fake_game_state

REGION = CaptureRegion(100, 50, 1920, 1200)


def _raises(exc_type, fn):
    try:
        fn()
    except exc_type:
        return
    raise AssertionError(f"應該拋出 {exc_type.__name__}")


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


class FakeMouse:
    def __init__(self) -> None:
        self.clicks: list[tuple[int, int]] = []

    def click(self, x: int, y: int) -> None:
        self.clicks.append((x, y))


class _Ids:
    def __init__(self) -> None:
        self.n = 0

    def next(self) -> str:
        self.n += 1
        return f"t_{self.n:04d}"


def blank(h=100, w=100):
    return np.zeros((h, w, 3), dtype=np.uint8)


def with_block(base, y0, y1, x0, x1, value=255):
    frame = base.copy()
    frame[y0:y1, x0:x1] = value
    return frame


def sequence(frames):
    """依序回傳 frames；用完後一直回傳最後一張。"""
    state = {"i": 0}

    def fn():
        i = min(state["i"], len(frames) - 1)
        state["i"] += 1
        return frames[i]

    return fn


def make_verifier(capture_fn, **kw):
    clock = FakeClock()
    params = dict(
        timeout=0.5, poll_interval=0.05, roi_margin=None, downsample=1,
        clock=clock, sleep=clock.sleep,
    )
    params.update(kw)
    return ActionVerifier(capture_fn, **params)


# ----------------------------------------------------------- 畫面差異 / 驗證器

def test_frame_diff_ratio():
    a = blank()
    b = with_block(a, 10, 20, 10, 20)  # 100 / 10000 像素不同

    assert frame_diff_ratio(a, a) == 0.0
    assert abs(frame_diff_ratio(a, b) - 0.01) < 1e-9
    # 差異小於 pixel_threshold 不算
    assert frame_diff_ratio(a, with_block(a, 10, 20, 10, 20, value=10), pixel_threshold=25) == 0.0
    # ROI：變化在 ROI 外不算；在 ROI 內只算 ROI 的比例（100 / 2500）
    assert frame_diff_ratio(a, b, roi=(50, 50, 100, 100)) == 0.0
    assert abs(frame_diff_ratio(a, b, roi=(0, 0, 50, 50)) - 0.04) < 1e-9
    _raises(ValueError, lambda: frame_diff_ratio(blank(100, 100), blank(50, 50)))


def test_verified_after_change_and_settle():
    base = blank()
    changed = with_block(base, 10, 20, 10, 20)
    verifier = make_verifier(sequence([base, base, changed, changed, changed]))

    assert verifier.prepare((15, 15)) is True
    result = verifier.wait()

    # 第 1 幀沒變、第 2 幀變化、第 3、4 幀連續穩定 -> 共 4 次擷取
    assert result.verified and result.changed and result.stable
    assert result.polls == 4 and result.error is None
    assert verifier.history == [result]


def test_no_change_times_out():
    base = blank()
    verifier = make_verifier(sequence([base]))
    verifier.prepare((15, 15))
    result = verifier.wait()

    assert not result.verified and result.changed is False
    assert result.error == ERR_ACTION_TIMEOUT


def test_changed_but_never_stable():
    base = blank()
    a = with_block(base, 10, 20, 10, 20)
    b = with_block(base, 30, 40, 30, 40)
    verifier = make_verifier(sequence([base] + [a, b] * 20))  # 畫面一直在閃
    verifier.prepare((15, 15))
    result = verifier.wait()

    assert result.changed is True and result.stable is False
    assert result.error == ERR_ACTION_NOT_STABLE


def test_frame_size_change_detected():
    verifier = make_verifier(sequence([blank(100, 100), blank(50, 50)]))
    verifier.prepare((15, 15))
    result = verifier.wait()

    assert result.error == ERR_FRAME_SIZE_CHANGED and result.polls == 1


def test_capture_failure():
    assert make_verifier(lambda: None).prepare((1, 1)) is False

    verifier = make_verifier(sequence([blank(), None]))
    assert verifier.prepare((1, 1)) is True
    assert verifier.wait().error == ERR_CAPTURE_FAILED


def test_roi_ignores_far_changes():
    base = blank(200, 200)
    far = with_block(base, 150, 190, 150, 190)
    near = with_block(base, 40, 60, 40, 60)

    far_verifier = make_verifier(sequence([base, far]), roi_margin=20)
    far_verifier.prepare((50, 50))
    assert far_verifier.wait().error == ERR_ACTION_TIMEOUT  # ROI 外的變化不算

    near_verifier = make_verifier(sequence([base, near]), roi_margin=20)
    near_verifier.prepare((50, 50))
    assert near_verifier.wait().verified


# --------------------------------------------------------------- 執行器整合

class FakeVerifier:
    def __init__(self, results, *, prepare_ok=True) -> None:
        self.results = list(results)
        self.prepare_ok = prepare_ok
        self.prepared: list = []

    def prepare(self, frame_point):
        self.prepared.append(frame_point)
        return self.prepare_ok

    def wait(self):
        return self.results.pop(0)


def ok():
    return VerifyResult(True, True, 10.0, 3, 0.02)


def bad(code=ERR_ACTION_TIMEOUT):
    return VerifyResult(False, False, 1000.0, 20, 0.0, code)


PLAN = PlannedClicks(((10, 20), (30, 40)), ((110, 70), (130, 90)))


def _exec(verifier, mouse, log_dir=None):
    ids = _Ids()
    logger = AppLogger(log_dir=str(log_dir), game_id="t") if log_dir is not None else None
    controller = AgentController(game_id="t", mouse=mouse, logger=logger)
    controller.start()
    try:
        return execute_action(
            "chi_1_2_3", 2, lambda: PLAN, controller,
            game_id="t", decision_id="d1", schema_action=None,
            next_event_id=ids.next, logger=logger, verifier=verifier,
        )
    finally:
        controller.stop()
        if logger is not None:
            logger.close()


def test_executor_verified_two_steps(tmp_path):
    mouse, verifier = FakeMouse(), FakeVerifier([ok(), ok()])
    receipt, _ = _exec(verifier, mouse, tmp_path)

    assert receipt.success is True and receipt.state_verified is True
    assert mouse.clicks == [(110, 70), (130, 90)]
    assert verifier.prepared == [(10, 20), (30, 40)]  # 每一步點擊前都擷取基準幀

    events = [json.loads(l) for l in (tmp_path / "t.jsonl").read_text(encoding="utf-8").splitlines()]
    completed = next(e for e in events if e["event_type"] == "action_completed")
    assert len(completed["metadata"]["verification"]) == 2
    assert "change_ratio" in completed["metadata"]["verification"][0]


def test_executor_last_step_timeout():
    mouse = FakeMouse()
    receipt, _ = _exec(FakeVerifier([ok(), bad()]), mouse)

    assert mouse.clicks == [(110, 70), (130, 90)]
    assert receipt.success is False and receipt.state_verified is False
    assert receipt.ui_action_executed is True
    assert receipt.error_code == ERR_ACTION_TIMEOUT
    assert receipt.should_stop is False  # 最後一步逾時：交給重試（D4）


def test_executor_first_step_timeout_stops_sequence():
    mouse = FakeMouse()
    receipt, _ = _exec(FakeVerifier([bad()]), mouse)

    assert mouse.clicks == [(110, 70)]  # 第一步沒確認，不點第二步
    assert receipt.success is False and receipt.error_code == ERR_ACTION_TIMEOUT
    assert receipt.should_stop is True  # 做到一半：畫面可能停在選單中間


def test_executor_prepare_failure_blocks_click():
    mouse = FakeMouse()
    receipt, _ = _exec(FakeVerifier([], prepare_ok=False), mouse)

    assert mouse.clicks == []
    assert receipt.error_code == ERR_CAPTURE_FAILED
    assert receipt.ui_action_executed is False and receipt.should_stop is True


def test_executor_frame_size_change_requests_stop():
    receipt, _ = _exec(FakeVerifier([ok(), bad(ERR_FRAME_SIZE_CHANGED)]), FakeMouse())

    assert receipt.error_code == ERR_FRAME_SIZE_CHANGED
    assert receipt.should_stop is True


# ------------------------------------------------------------ pipeline 整合

def _discard_run(frame_changes_on_click, log_dir, game_id):
    state = make_fake_game_state(game_id)
    mapper = TileMapper(frame_size=(1920, 1200))
    mapper.update(
        [TileBox(t, 100 + i * 30, 600, 26, 40) for i, t in enumerate(sorted(state.players[SEAT].hand))]
    )

    mouse = FakeMouse()
    blank_frame = np.zeros((1200, 1920, 3), dtype=np.uint8)
    changed_frame = blank_frame.copy()
    changed_frame[590:650, 90:170] = 255  # 蓋住牌 0（中心 113,620）附近

    def capture():
        return changed_frame if (frame_changes_on_click and mouse.clicks) else blank_frame

    clock = FakeClock()
    verifier = ActionVerifier(capture, timeout=0.5, poll_interval=0.05, clock=clock, sleep=clock.sleep)

    with AppLogger(log_dir=str(log_dir), game_id=game_id) as logger:
        controller = AgentController(game_id=game_id, mouse=mouse, logger=logger)
        controller.start()
        try:
            result = run_discard_turn(
                state, SEAT, mapper, REGION, controller,
                game_id=game_id, ids=EventIds(), logger=logger, verifier=verifier,
            )
        finally:
            controller.stop()

    return result, mouse


def test_pipeline_discard_verified(tmp_path):
    result, mouse = _discard_run(True, tmp_path, "t_v_ok")

    assert result.success is True
    assert result.receipt.state_verified is True
    assert mouse.clicks == [(213, 670)]


def test_pipeline_discard_no_change_times_out(tmp_path):
    result, mouse = _discard_run(False, tmp_path, "t_v_bad")

    assert mouse.clicks == [(213, 670)]  # 有點擊，但沒確認
    assert result.success is False
    assert result.error == ERR_ACTION_TIMEOUT
    assert result.receipt.state_verified is False
    assert result.receipt.ui_action_executed is True


if __name__ == "__main__":
    test_frame_diff_ratio()
    test_verified_after_change_and_settle()
    test_no_change_times_out()
    test_changed_but_never_stable()
    test_frame_size_change_detected()
    test_capture_failure()
    test_roi_ignores_far_changes()
    with tempfile.TemporaryDirectory() as d:
        base = Path(d)
        test_executor_verified_two_steps(base / "a")
        test_executor_last_step_timeout()
        test_executor_first_step_timeout_stops_sequence()
        test_executor_prepare_failure_blocks_click()
        test_executor_frame_size_change_requests_stop()
        test_pipeline_discard_verified(base / "b")
        test_pipeline_discard_no_change_times_out(base / "c")
    print("✅ test_verifier：14 項測試全部通過")