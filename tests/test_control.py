"""W1 capture/click/pause/stop 最小 smoke test。"""

from src.control.controller import AgentController, ControlState


class FakeMouse:
    def __init__(self) -> None:
        self.clicks: list[tuple[int, int]] = []

    def click(self, x: int, y: int) -> None:
        self.clicks.append((x, y))


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
