"""畫面擷取抽象層。

W2 先提供最小 capture 介面：擷取整個螢幕或指定區域，回傳 BGR numpy 影像，
並可存成 PNG。之後再加入固定視窗定位（W3 D2）、穩定畫面判斷與多幀確認。

B2：實測整個視窗約 75ms、只抓 300x300 約 8ms，所以新增 grab_roi()，
讓驗證輪詢只抓點擊點附近。

注意：這裡只負責「取得畫面」，不做牌面辨識（視覺模組負責）。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np

# (x0, y0, x1, y1)，相對於「擷取畫面（frame）」的像素座標，x1 / y1 不含
Roi = tuple[int, int, int, int]


@dataclass(frozen=True)
class CaptureRegion:
    """螢幕上的擷取範圍（像素）。"""

    left: int
    top: int
    width: int
    height: int

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise ValueError("width and height must be positive")

    def as_mss(self) -> dict[str, int]:
        return {
            "left": self.left,
            "top": self.top,
            "width": self.width,
            "height": self.height,
        }


# 擷取函式：輸入 mss 區域 dict 或 None（整個螢幕），回傳 HxWx3 或 HxWx4 陣列
GrabFn = Callable[[CaptureRegion | None], np.ndarray]


def _mss_grab(region: CaptureRegion | None, monitor: int) -> np.ndarray:
    """預設後端：使用 mss 擷取畫面。延後 import，沒裝 mss 時也能載入本模組。"""
    import mss

    # mss.mss 已被標示為即將移除，新版用 mss.MSS；舊版沒有 MSS 時退回 mss.mss
    factory = getattr(mss, "MSS", None) or mss.mss

    with factory() as sct:
        target = region.as_mss() if region is not None else sct.monitors[monitor]
        return np.array(sct.grab(target))


def _to_bgr(frame: np.ndarray) -> np.ndarray:
    if frame.ndim != 3 or frame.shape[2] not in (3, 4):
        raise ValueError(f"unexpected frame shape: {frame.shape}")

    # mss 回傳 BGRA，去掉 alpha 後與 cv2.imread 的 BGR 格式一致
    return frame[:, :, :3]


class ScreenCapture:
    """mss 的薄包裝，方便之後替換成測試 fake。"""

    def __init__(
        self,
        *,
        region: CaptureRegion | None = None,
        monitor: int = 1,
        grab_fn: GrabFn | None = None,
    ) -> None:
        self.region = region
        self.monitor = monitor
        self._grab_fn = grab_fn or (lambda r: _mss_grab(r, self.monitor))

    def grab(self) -> np.ndarray:
        """擷取一張畫面，回傳 BGR、shape 為 (高, 寬, 3) 的 numpy 陣列。"""
        return _to_bgr(self._grab_fn(self.region))

    def grab_roi(self, roi: Roi) -> np.ndarray:
        """只擷取 frame 內的一塊區域（roi 為 frame 座標），回傳 BGR、shape 為 (高, 寬, 3)。

        有固定視窗區域時，換算成螢幕座標後只抓那一塊（快很多）；
        沒有固定區域（整個螢幕）時，不知道原點，退回整張擷取再裁切。
        """
        x0, y0, x1, y1 = roi
        if x1 <= x0 or y1 <= y0:
            raise ValueError(f"invalid roi: {roi}")

        if self.region is None:
            return self.grab()[y0:y1, x0:x1]

        sub = CaptureRegion(self.region.left + x0, self.region.top + y0, x1 - x0, y1 - y0)
        return _to_bgr(self._grab_fn(sub))

    def save(self, path: str | Path) -> Path:
        """擷取並存成圖檔，回傳實際路徑。"""
        import cv2

        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)

        if not cv2.imwrite(str(target), self.grab()):
            raise RuntimeError(f"failed to write image: {target}")

        return target