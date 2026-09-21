from src.control.controller import AgentController, ControlState


class FakeMouse:
    def __init__(self) -> None:
        self.clicks: list[tuple[int, int]] = []

    def click(self, x: int, y: int) -> None:
        self.clicks.append((x, y))


def test_start_and_click() -> None:
    mouse = FakeMouse()
    controller = AgentController(mouse=mouse)

    controller.start()

    assert controller.state == ControlState.RUNNING
    assert controller.click(100, 200) is True
    assert mouse.clicks == [(100, 200)]


def test_pause_blocks_click_until_resume() -> None:
    mouse = FakeMouse()
    controller = AgentController(mouse=mouse)

    controller.start()
    controller.pause()

    assert controller.state == ControlState.PAUSED
    assert controller.click(100, 200) is False
    assert mouse.clicks == []

    controller.resume()

    assert controller.state == ControlState.RUNNING
    assert controller.click(100, 200) is True
    assert mouse.clicks == [(100, 200)]


def test_stop_blocks_future_clicks() -> None:
    mouse = FakeMouse()
    controller = AgentController(mouse=mouse)

    controller.start()
    controller.stop()

    assert controller.state == ControlState.STOPPED
    assert controller.click(100, 200) is False
    assert mouse.clicks == []


def test_stopped_controller_cannot_restart() -> None:
    controller = AgentController(mouse=FakeMouse())

    controller.start()
    controller.stop()

    try:
        controller.start()
    except RuntimeError:
        pass
    else:
        raise AssertionError("A stopped controller must not restart.")
