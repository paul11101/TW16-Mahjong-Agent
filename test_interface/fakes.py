"""
測試介面與測試共用的假物件。
"""

from __future__ import annotations


class FakeMouse:
    """記錄點擊位置，不會真的操作滑鼠。"""

    def __init__(self) -> None:
        self.clicks: list[tuple[int, int]] = []

    def click(self, x: int, y: int) -> None:
        self.clicks.append((x, y))