"""W1 capture/click/pause/stop 最小 smoke test。

執行方式（專案根目錄）：
    python -m tests.test_control
或
    python -m pytest tests/test_control.py -v
"""

import numpy as np

from src.control.capture import ScreenCapture
from src.control.controller import AgentController, ControlState


class FakeMouse:
    def __init__(self) -> None:
        self.clicks: list[tuple[int, int]] = []

    def click(self, x: int, y: int) -> None:
        self.clicks.append((x, y))


def make_fake_capturer() -> ScreenCapture:
    return ScreenCapture(grab_fn=lambda region: np.zeros((20, 30, 4), dtype=np.uint8))


def test_control_lifecycle() -> None:
    mouse = FakeMouse()
    controller = AgentController(mouse=mouse)

    assert controller.state == ControlState.IDLE

    controller.start()
    assert controller.click(10, 20) is True

    controller.pause()
    assert controller.click(30, 40) is False

    controller.resume()
    assert controller.click(50, 60) is True

    controller.stop()
    assert controller.click(70, 80) is False

    assert mouse.clicks == [(10, 20), (50, 60)]


def test_capture_gated_by_stop() -> None:
    controller = AgentController(mouse=FakeMouse(), capturer=make_fake_capturer())

    controller.start()
    assert controller.capture().shape == (20, 30, 3)

    controller.pause()
    assert controller.capture() is not None

    controller.stop()
    assert controller.capture() is None


if __name__ == "__main__":
    test_control_lifecycle()
    test_capture_gated_by_stop()
    print("✅ test_control：2 項測試全部通過")