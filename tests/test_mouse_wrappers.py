"""W7 整理：CountingMouse、RepeatClickMouse、MouseController.move 的測試（假 pyautogui）。

執行方式（專案根目錄）：
    python -m tests.test_mouse_wrappers
或
    python -m pytest tests/test_mouse_wrappers.py -v
"""

import types

import pytest

from src.control.mouse import CountingMouse, MouseController, RepeatClickMouse
from test_interface.fakes import FakeMouse
from tests._runner import run_module
from tests.test_mouse import _FakePyAutoGui


def test_counting_mouse_counts_and_records_points():
    inner = FakeMouse()
    mouse = CountingMouse(inner)
    mouse.click(1, 2)
    mouse.click(3, 4)

    assert mouse.count == 2
    assert mouse.points == [(1, 2), (3, 4)]
    assert inner.clicks == [(1, 2), (3, 4)]


def test_counting_mouse_skips_failed_click():
    class Boom:
        def click(self, x, y):
            raise RuntimeError("failsafe")

    mouse = CountingMouse(Boom())
    with pytest.raises(RuntimeError):
        mouse.click(1, 2)
    assert mouse.count == 0 and mouse.points == []


def test_repeat_click_mouse():
    inner, sleeps = FakeMouse(), []
    RepeatClickMouse(inner, times=2, gap=0.25, sleep=sleeps.append).click(5, 6)
    assert inner.clicks == [(5, 6), (5, 6)] and sleeps == [0.25]

    single = FakeMouse()
    RepeatClickMouse(single, times=1, sleep=sleeps.append).click(1, 2)
    assert single.clicks == [(1, 2)]

    with pytest.raises(ValueError):
        RepeatClickMouse(FakeMouse(), times=0)


def test_counting_over_repeat_counts_logical_clicks():
    inner = FakeMouse()
    mouse = CountingMouse(RepeatClickMouse(inner, times=2, sleep=lambda s: None))
    mouse.click(5, 6)

    assert mouse.count == 1  # 連點兩下算同一次動作
    assert inner.clicks == [(5, 6), (5, 6)]


def test_mouse_controller_move_forwards_to_pyautogui():
    calls = []
    module = types.ModuleType("pyautogui")
    module.moveTo = lambda x, y, duration: calls.append((x, y, duration))

    with _FakePyAutoGui(module):
        MouseController().move(7, 8)
        MouseController().move(1, 2, duration=0.0)

    assert calls == [(7, 8, 0.4), (1, 2, 0.0)]


if __name__ == "__main__":
    run_module(globals(), "test_mouse_wrappers")