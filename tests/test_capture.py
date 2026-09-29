"""W2 capture 最小 smoke test（不需要真實螢幕）。"""

import numpy as np
import pytest

from src.control.capture import CaptureRegion, ScreenCapture


def make_fake_grab(calls: list):
    def fake_grab(region):
        calls.append(region)
        # 模擬 mss 的 BGRA 輸出：高 20、寬 30
        return np.zeros((20, 30, 4), dtype=np.uint8)

    return fake_grab


def test_grab_returns_bgr_frame() -> None:
    calls: list = []
    capture = ScreenCapture(grab_fn=make_fake_grab(calls))

    frame = capture.grab()

    assert frame.shape == (20, 30, 3)
    assert calls == [None]


def test_grab_passes_region() -> None:
    calls: list = []
    region = CaptureRegion(left=10, top=20, width=30, height=20)
    capture = ScreenCapture(region=region, grab_fn=make_fake_grab(calls))

    capture.grab()

    assert calls == [region]
    assert region.as_mss() == {"left": 10, "top": 20, "width": 30, "height": 20}


def test_invalid_region_rejected() -> None:
    with pytest.raises(ValueError):
        CaptureRegion(left=0, top=0, width=0, height=10)


def test_save_writes_png(tmp_path) -> None:
    capture = ScreenCapture(grab_fn=make_fake_grab([]))

    path = capture.save(tmp_path / "shots" / "frame.png")

    assert path.exists()