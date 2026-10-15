"""B2 ROI 擷取測試：ScreenCapture.grab_roi、controller.capture_roi、ActionVerifier 的 ROI 模式。

全部使用合成畫面與假時鐘，不需要瀏覽器。執行方式（專案根目錄）：
    python -m tests.test_verifier_roi
或
    python -m pytest tests/test_verifier_roi.py -v
"""

import numpy as np
import pytest

from src.control.capture import CaptureRegion, ScreenCapture
from src.control.controller import AgentController
from src.control.verifier import (
    ERR_ACTION_TIMEOUT,
    ERR_CAPTURE_FAILED,
    ERR_FRAME_SIZE_CHANGED,
    ActionVerifier,
)
from test_interface.fakes import FakeMouse
from tests._runner import run_module
from tests.helpers import FakeClock


def blank(h=200, w=200):
    return np.zeros((h, w, 3), dtype=np.uint8)


def with_block(base, y0, y1, x0, x1, value=255):
    frame = base.copy()
    frame[y0:y1, x0:x1] = value
    return frame


def roi_world(frames):
    """假的 ROI 擷取：依序回傳 frames 裁出的 ROI，並記錄每次要求的 ROI。"""
    state = {"i": 0}
    seen = []

    def capture_roi(roi):
        x0, y0, x1, y1 = roi
        i = min(state["i"], len(frames) - 1)
        state["i"] += 1
        seen.append(roi)
        return frames[i][y0:y1, x0:x1]

    return capture_roi, seen


def _no_full_capture():
    raise AssertionError("ROI 模式不應該擷取整個視窗")


def make_roi_verifier(capture_roi, **kw):
    clock = FakeClock()
    params = dict(
        timeout=0.5, poll_interval=0.05, roi_margin=20, downsample=1,
        roi_capture_fn=capture_roi, frame_size=(200, 200),
        clock=clock, sleep=clock.sleep,
    )
    params.update(kw)
    return ActionVerifier(_no_full_capture, **params)


# ------------------------------------------------------- ScreenCapture.grab_roi

def test_grab_roi_converts_to_screen_region():
    seen = []

    def fake_grab(region):
        seen.append(region)
        return np.zeros((region.height, region.width, 4), dtype=np.uint8)

    capture = ScreenCapture(region=CaptureRegion(100, 50, 800, 600), grab_fn=fake_grab)
    frame = capture.grab_roi((10, 20, 40, 60))

    assert frame.shape == (40, 30, 3)  # 高 40、寬 30、去掉 alpha
    assert seen == [CaptureRegion(110, 70, 30, 40)]  # frame 座標加視窗左上角


def test_grab_roi_without_region_crops_full_frame():
    full = np.zeros((100, 200, 4), dtype=np.uint8)
    full[25, 45, 0] = 9

    capture = ScreenCapture(grab_fn=lambda region: full)
    frame = capture.grab_roi((40, 20, 60, 40))

    assert frame.shape == (20, 20, 3)
    assert frame[5, 5, 0] == 9


def test_grab_roi_rejects_empty_roi():
    capture = ScreenCapture(region=CaptureRegion(0, 0, 100, 100), grab_fn=lambda r: np.zeros((1, 1, 4)))
    with pytest.raises(ValueError):
        capture.grab_roi((10, 10, 10, 20))


def test_controller_capture_roi_gated_by_stop():
    capture = ScreenCapture(
        region=CaptureRegion(0, 0, 30, 20),
        grab_fn=lambda r: np.zeros((r.height, r.width, 4), dtype=np.uint8),
    )
    controller = AgentController(mouse=FakeMouse(), capturer=capture)

    controller.start()
    assert controller.capture_roi((0, 0, 10, 5)).shape == (5, 10, 3)

    controller.pause()
    assert controller.capture_roi((0, 0, 10, 5)) is not None  # 暫停仍可觀察

    controller.stop()
    assert controller.capture_roi((0, 0, 10, 5)) is None


# ---------------------------------------------------------- ActionVerifier ROI 模式

def test_roi_mode_verified_and_never_captures_full_frame():
    base = blank()
    near = with_block(base, 40, 60, 40, 60)
    capture_roi, seen = roi_world([base, base, near, near, near])
    verifier = make_roi_verifier(capture_roi)

    assert verifier.roi_mode is True
    assert verifier.prepare((50, 50)) is True
    result = verifier.wait()

    assert result.verified and result.polls == 4 and result.error is None
    assert set(seen) == {(30, 30, 70, 70)}  # 每次都只要求同一塊 ROI


def test_roi_mode_ignores_changes_outside_roi():
    base = blank()
    far = with_block(base, 150, 190, 150, 190)
    capture_roi, _ = roi_world([base, far])
    verifier = make_roi_verifier(capture_roi)

    verifier.prepare((50, 50))
    assert verifier.wait().error == ERR_ACTION_TIMEOUT


def test_roi_is_clamped_to_frame():
    capture_roi, seen = roi_world([blank()])
    verifier = make_roi_verifier(capture_roi)

    assert verifier.prepare((5, 5)) is True
    assert verifier.prepare((195, 195)) is True
    assert seen == [(0, 0, 25, 25), (175, 175, 200, 200)]


def test_region_guard_false_blocks_prepare():
    capture_roi, seen = roi_world([blank()])
    verifier = make_roi_verifier(capture_roi, region_guard=lambda: False)

    assert verifier.prepare((50, 50)) is False
    assert seen == []  # 視窗已改變，連擷取都不做


def test_region_moved_before_success_is_frame_size_changed():
    base = blank()
    near = with_block(base, 40, 60, 40, 60)
    capture_roi, _ = roi_world([base, base, near, near, near])
    answers = iter([True, False])  # prepare 時沒問題，驗證成功前視窗被移動
    verifier = make_roi_verifier(capture_roi, region_guard=lambda: next(answers))

    assert verifier.prepare((50, 50)) is True
    result = verifier.wait()

    assert result.error == ERR_FRAME_SIZE_CHANGED
    assert result.verified is False


def test_roi_capture_failures():
    assert make_roi_verifier(lambda roi: None).prepare((50, 50)) is False

    base = blank()
    state = {"i": 0}

    def flaky(roi):
        state["i"] += 1
        return base[roi[1]:roi[3], roi[0]:roi[2]] if state["i"] == 1 else None

    verifier = make_roi_verifier(flaky)
    assert verifier.prepare((50, 50)) is True
    assert verifier.wait().error == ERR_CAPTURE_FAILED


def test_full_window_mode_when_roi_args_missing():
    verifier = ActionVerifier(lambda: blank(), roi_margin=20)
    assert verifier.roi_mode is False


if __name__ == "__main__":
    run_module(globals(), "test_verifier_roi")