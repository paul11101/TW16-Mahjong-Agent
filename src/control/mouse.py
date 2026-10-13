"""滑鼠操作抽象層。

W1 先提供最小 click 介面，後續再加入座標映射、ActionReceipt、
操作後畫面驗證與 retry/timeout。

pyautogui 延後到 click() 才 import：沒裝 pyautogui 或沒有顯示器的環境
（例如只跑單元測試）也能載入本模組，做法與 capture.py 一致。
"""

from __future__ import annotations


class MouseController:
    """PyAutoGUI 的薄包裝，方便之後替換成測試 fake。"""

    def __init__(self, *, duration: float = 0.0) -> None:
        self.duration = duration

    def click(self, x: int, y: int) -> None:
        import pyautogui

        pyautogui.click(x=x, y=y, duration=self.duration)