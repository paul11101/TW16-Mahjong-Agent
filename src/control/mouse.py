"""滑鼠操作抽象層。

pyautogui 延後到 click() 才 import：沒裝 pyautogui 或沒有顯示器的環境
（例如只跑單元測試）也能載入本模組。但 import pyautogui 要數百毫秒，
實機流程請在計時開始前呼叫 warmup()（live_common.make_mouse 已經會做）。

包裝類別（都只需要 inner.click(x, y)）：
- RepeatClickMouse：同一座標連點 times 次（給「第一下選牌、第二下打出」的遊戲）。
- CountingMouse：記錄「邏輯上的點擊」次數與座標；GameRunner 用它統計實際點擊數與重複點擊。
"""

from __future__ import annotations

import time
from typing import Any, Callable


class MouseController:
    """PyAutoGUI 的薄包裝，方便之後替換成測試 fake。"""

    def __init__(self, *, duration: float = 0.0) -> None:
        self.duration = duration

    def warmup(self) -> None:
        """提前載入 pyautogui，避免第一次點擊多花 import 的時間。沒裝 pyautogui 會拋 ImportError。"""
        import pyautogui  # noqa: F401

    def click(self, x: int, y: int) -> None:
        import pyautogui

        pyautogui.click(x=x, y=y, duration=self.duration)

    def move(self, x: int, y: int, *, duration: float = 0.4) -> None:
        """只移動不點擊（hover 檢查座標用）。"""
        import pyautogui

        pyautogui.moveTo(x, y, duration=duration)


class RepeatClickMouse:
    """同一個座標連點 times 次（click 一次 = 實體點 times 次）。"""

    def __init__(
        self, inner: Any, times: int = 2, gap: float = 0.25,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if times < 1:
            raise ValueError("times 必須 >= 1")
        self._inner = inner
        self.times = times
        self.gap = gap
        self._sleep = sleep

    def click(self, x: int, y: int) -> None:
        for i in range(self.times):
            if i:
                self._sleep(self.gap)
            self._inner.click(x, y)


class CountingMouse:
    """記錄點擊次數與座標。inner 點擊成功（沒拋例外）才計數。"""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.count = 0
        self.points: list[tuple[int, int]] = []

    def click(self, x: int, y: int) -> None:
        self._inner.click(x, y)
        self.count += 1
        self.points.append((x, y))