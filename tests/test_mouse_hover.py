"""MouseController 的 hover 等待：先移動、等待，再點擊（假 pyautogui）。

執行方式（專案根目錄）：
    python -m tests.test_mouse_hover
"""

import types

from src.control.mouse import MouseController
from tests._runner import run_module
from tests.test_mouse import _FakePyAutoGui


def _module(calls):
    module = types.ModuleType("pyautogui")
    module.moveTo = lambda x, y, duration: calls.append(("move", x, y, duration))
    module.click = lambda x, y, duration=None: calls.append(("click", x, y))
    return module


def test_hover_moves_waits_then_clicks():
    calls, sleeps = [], []
    with _FakePyAutoGui(_module(calls)):
        MouseController(duration=0.05, hover_delay=0.15, sleep=sleeps.append).click(3, 4)

    assert calls == [("move", 3, 4, 0.05), ("click", 3, 4)]
    assert sleeps == [0.15]


def test_no_hover_keeps_old_single_click():
    calls, sleeps = [], []
    with _FakePyAutoGui(_module(calls)):
        MouseController(sleep=sleeps.append).click(3, 4)

    assert calls == [("click", 3, 4)]  # 沒有 moveTo、沒有等待
    assert sleeps == []


if __name__ == "__main__":
    run_module(globals(), "test_mouse_hover")