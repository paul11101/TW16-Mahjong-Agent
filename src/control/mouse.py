"""滑鼠操作抽象層。

W1 先提供最小 click 介面，後續再加入座標映射、ActionReceipt、
操作後畫面驗證與 retry/timeout。
"""

from __future__ import annotations

import pyautogui


class MouseController:
    """PyAutoGUI 的薄包裝，方便之後替換成測試 fake。"""

    def __init__(self, *, duration: float = 0.0) -> None:
        self.duration = duration

    def click(self, x: int, y: int) -> None:
        pyautogui.click(x=x, y=y, duration=self.duration)
