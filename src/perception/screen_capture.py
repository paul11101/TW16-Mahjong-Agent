"""螢幕擷取抽象層。

W1 只負責提供 capture() 骨架；後續再加入 ROI、DPI/視窗定位與
OpenCV 辨識。capture 不負責判斷麻將規則。
"""

from __future__ import annotations

from dataclasses import dataclass

import mss
import numpy as np


@dataclass(frozen=True)
class ScreenFrame:
    image: np.ndarray
    left: int
    top: int
    width: int
    height: int


class ScreenCapture:
    def __init__(self) -> None:
        self._sct = mss.mss()

    def capture(self, monitor: dict[str, int] | None = None) -> ScreenFrame:
        """擷取指定螢幕區域；未指定時擷取第一個螢幕。"""
        target = monitor or self._sct.monitors[1]
        shot = self._sct.grab(target)
        image = np.asarray(shot)

        return ScreenFrame(
            image=image,
            left=target["left"],
            top=target["top"],
            width=target["width"],
            height=target["height"],
        )

    def close(self) -> None:
        self._sct.close()

    def __enter__(self) -> "ScreenCapture":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()
