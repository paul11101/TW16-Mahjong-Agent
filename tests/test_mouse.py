"""MouseController 測試：用假的 pyautogui 模組，不會真的動滑鼠、也不需要安裝 pyautogui。

執行方式（專案根目錄）：
    python -m tests.test_mouse
或
    python -m pytest tests/test_mouse.py -v
"""

import sys
import types

import pytest

from src.control.mouse import MouseController
from tests._runner import run_module


class _FakePyAutoGui:
    """暫時把 sys.modules['pyautogui'] 換成假模組（None = 模擬沒安裝），結束後還原。"""

    def __init__(self, module) -> None:
        self.module = module
        self._missing = object()
        self._old = self._missing

    def __enter__(self):
        self._old = sys.modules.get("pyautogui", self._missing)
        sys.modules["pyautogui"] = self.module
        return self.module

    def __exit__(self, *exc) -> None:
        if self._old is self._missing:
            sys.modules.pop("pyautogui", None)
        else:
            sys.modules["pyautogui"] = self._old


def _fake_module(calls):
    module = types.ModuleType("pyautogui")
    module.click = lambda x, y, duration: calls.append((x, y, duration))
    return module


def test_click_forwards_to_pyautogui():
    calls = []
    with _FakePyAutoGui(_fake_module(calls)):
        MouseController(duration=0.1).click(3, 4)

    assert calls == [(3, 4, 0.1)]


def test_warmup_loads_pyautogui_without_clicking():
    calls = []
    with _FakePyAutoGui(_fake_module(calls)):
        MouseController().warmup()

    assert calls == []  # 只載入，不點擊


def test_construct_does_not_import_pyautogui():
    # None 代表「import 會失敗」；建立物件不該碰 pyautogui（沒裝或沒顯示器也能跑測試）
    with _FakePyAutoGui(None):
        mouse = MouseController()
        with pytest.raises(ImportError):
            mouse.warmup()
        with pytest.raises(ImportError):
            mouse.click(1, 2)


if __name__ == "__main__":
    run_module(globals(), "test_mouse")