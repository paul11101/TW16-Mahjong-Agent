"""測試專用的共用輔助（只給 tests/ 使用；src/ 與 test_interface/ 不可以 import 這個檔案）。

pytest 只會收集 test_*.py，所以這個檔案不會被當成測試執行。
"""

from __future__ import annotations

from typing import Sequence

from src.control.tile_mapper import TileBox, TileMapper
from test_interface.fakes import FakeMouse

FRAME_SIZE = (1920, 1200)
CHI_IDS = ["chi_0_1_2", "chi_1_2_3", "chi_2_3_4"]


class FakeClock:
    """假時鐘：sleep 只會把時間往前推，不會真的等待。"""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


class PauseAfterFirstClickMouse(FakeMouse):
    """第一次點擊後把 controller 暫停，模擬「兩步驟做到一半被暫停」。"""

    controller = None

    def click(self, x: int, y: int) -> None:
        super().click(x, y)
        if len(self.clicks) == 1 and self.controller is not None:
            self.controller.pause()


def hand_boxes(hand: Sequence[int]) -> list[TileBox]:
    """手牌由小到大排序後，橫向排列的合成牌框（牌 0 的中心 = (113, 620)）。"""
    return [TileBox(t, 100 + i * 30, 600, 26, 40) for i, t in enumerate(sorted(hand))]


def make_hand_mapper(hand: Sequence[int], frame_size: tuple[int, int] = FRAME_SIZE) -> TileMapper:
    mapper = TileMapper(frame_size=frame_size)
    mapper.update(hand_boxes(hand))
    return mapper


def make_button_layout(disabled=("kong", "win")) -> dict:
    """合成的 /api/layout（只有按鈕與吃牌組合）：dpr 1.5、outer 1280x800、inner 1264x700。"""
    names = ["chi", "pong", "kong", "win", "pass"]
    return {
        "dpr": 1.5,
        "inner": [1264, 700],
        "outer": [1280, 800],
        "buttons": [
            {"action": n, "enabled": n not in disabled, "x": 100 + i * 60, "y": 500, "w": 50, "h": 30}
            for i, n in enumerate(names)
        ],
        "choices": [
            {"id": cid, "x": 100 + i * 100, "y": 560, "w": 80, "h": 20}
            for i, cid in enumerate(CHI_IDS)
        ],
    }