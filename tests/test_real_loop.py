"""以合成畫面和假滑鼠測試純截圖模式的反應辨識、點擊及逾時診斷。"""

import sys
from types import SimpleNamespace

import cv2
import numpy as np

from src.control.capture import CaptureRegion, ScreenCapture
from src.perception.detector import MahjongDetector
from test_interface import live_common, run_real_loop
from tests.test_vision_turns import S16, S17


def test_detects_larger_cancel_button(tmp_path):
    """較大的取消圖樣應以正確位置回傳，只有背景時則無按鈕。"""
    template = np.random.default_rng(0).integers(0, 256, (315, 320, 3), dtype=np.uint8)
    (tmp_path / "btn_pass.png").write_bytes(cv2.imencode(".png", template)[1].tobytes())
    detector = MahjongDetector(template_dir=str(tmp_path))
    frame = np.zeros((1980, 3550, 3), dtype=np.uint8)
    assert detector.detect_full_state(frame)["action_buttons"] == []

    enlarged = cv2.resize(template, (352, 346))
    frame[1138:1484, 2744:3096] = enlarged
    (button,) = detector.detect_full_state(frame)["action_buttons"]
    x, y, width, height = button["bbox"]
    assert button["name"] == "btn_pass"
    assert abs(x - 2744) <= 3 and abs(y - 1138) <= 3
    assert (width, height) == (352, 346)


def setup_loop(monkeypatch, tmp_path, states, *args):
    """接好 runner 的假視窗與滑鼠，依實際滑鼠點擊次數提供辨識結果。"""
    points = []
    region = CaptureRegion(5, 7, 400, 100)
    frame = np.zeros((region.height, region.width, 3), dtype=np.uint8)
    session = live_common.LiveSession(
        locator=SimpleNamespace(is_foreground=lambda: True),
        capturer=ScreenCapture(region=region, grab_fn=lambda _: frame),
        region=region,
        frame=frame,
    )

    class FakeMouse:
        """記錄每一次送到滑鼠的座標。"""

        def __init__(self, **kwargs):
            pass

        def warmup(self):
            pass

        def click(self, x, y):
            points.append((x, y))

    class FakeDetector:
        """依已點擊次數切換 runner 讀到的牌桌狀態。"""

        base_height = 100

        def __init__(self, **kwargs):
            pass

        def detect_full_state(self, frame, scan_secondary_rois=False):
            return states[min(len(points), len(states) - 1)]

    monkeypatch.setattr(live_common, "MouseController", FakeMouse)
    monkeypatch.setattr(run_real_loop, "MouseController", FakeMouse, raising=False)
    monkeypatch.setattr(run_real_loop, "MahjongDetector", FakeDetector)
    monkeypatch.setattr(run_real_loop, "open_session", lambda _: session)
    monkeypatch.setattr(sys, "argv", [
        "run_real_loop", "--log-dir", str(tmp_path), "--no-hotkeys", "--click-gap", "0", *args,
    ])
    return points


def test_reaction_click_is_single_and_discard_still_double_clicks(monkeypatch, tmp_path):
    cancel = {**S16, "action_buttons": [
        {"name": "btn_pass", "bbox": (300, 40, 30, 20), "confidence": 0.95},
    ]}
    points = setup_loop(
        monkeypatch, tmp_path, [cancel, S17], "--max-steps", "2", "--no-verify",
    )
    run_real_loop.main()

    cancel_point, discard_first, discard_second = points
    assert cancel_point == (320, 57)
    assert discard_first == discard_second and discard_first[1] == 82


def test_timeout_saves_before_and_after_images(monkeypatch, tmp_path):
    points = setup_loop(
        monkeypatch, tmp_path, [S17], "--max-steps", "5", "--full-verify",
        "--verify-timeout", "0.01", "--grace", "0", "--pause-timeout", "0.01", "--poll", "0.005",
    )
    assert run_real_loop.main() == 1
    assert len(points) == 2

    (before,) = tmp_path.glob("*_ACTION_TIMEOUT_before.png")
    (after,) = tmp_path.glob("*_ACTION_TIMEOUT.png")
    decode = cv2.IMREAD_COLOR
    before_image = cv2.imdecode(np.frombuffer(before.read_bytes(), dtype=np.uint8), decode)
    after_image = cv2.imdecode(np.frombuffer(after.read_bytes(), dtype=np.uint8), decode)
    assert before_image.shape == after_image.shape == (100, 400, 3)
    assert not before_image.any() and after_image.any()
