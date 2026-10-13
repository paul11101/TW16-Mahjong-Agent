"""座標共用工具：牌框／按鈕框都用同一套規則。

- Point：frame 或螢幕座標的 (x, y)。
- CenterMixin：給有 x / y / w / h 的 frozen dataclass 加上 center 屬性。
  用 mixin 而不是繼承欄位，所以 ButtonBox("chi", x, y, w, h) 的位置參數順序不變。
- ensure_inside：中心點是否在擷取畫面內。
- default_viewport_offset / dom_origin / dom_rect_to_frame：
  測試介面 DOM（CSS px、相對網頁可視區）轉成 frame 像素。

本模組不依賴 tile_mapper / button_mapper，避免循環 import。
"""

from __future__ import annotations

from typing import Any

Point = tuple[int, int]


class CenterMixin:
    """需要 self.x / self.y / self.w / self.h。"""

    @property
    def center(self) -> Point:
        return self.x + self.w // 2, self.y + self.h // 2  # type: ignore[attr-defined]


def ensure_inside(
    frame_size: tuple[int, int] | None,
    center: Point,
    name: str,
    exc_type: type[Exception],
) -> None:
    """中心不在 frame 內就拋 exc_type；frame_size 為 None 代表不檢查。"""
    if frame_size is None:
        return

    width, height = frame_size
    cx, cy = center
    if not (0 <= cx < width and 0 <= cy < height):
        raise exc_type(f"{name} 的中心 {center} 不在畫面 {width}x{height} 內")


def default_viewport_offset(layout: dict[str, Any]) -> tuple[float, float]:
    """網頁可視區左上角，在「視窗客戶區 frame」內的偏移（CSS px）。

    客戶區包含瀏覽器分頁列與網址列（見 window.py），網頁內容從更下方開始：
    - 左側 ≈ (outer寬 - inner寬) / 2
    - 上方 ≈ outer高 - inner高 - 下邊框（下邊框以左側邊框估計）
    這是估計值；有誤差時請看 debug 圖，並用 offset 參數覆蓋。
    """
    inner = layout.get("inner")
    outer = layout.get("outer")
    if not inner or not outer:
        return 0.0, 0.0

    border = max(0.0, (outer[0] - inner[0]) / 2)
    top = max(0.0, outer[1] - inner[1] - border)
    return border, top


def dom_origin(
    layout: dict[str, Any],
    *,
    offset: tuple[float, float] | None = None,
    scale: float | None = None,
    origin_px: tuple[float, float] | None = None,
) -> tuple[float, float, float]:
    """回傳 (dpr, 可視區原點 x_px, y_px)。

    可視區原點來源優先順序：
    1. origin_px：frame 像素（通常來自校正標記，最準）。
    2. offset：手動指定（CSS px）。
    3. 都沒給：用 default_viewport_offset() 估計。
    """
    dpr = float(scale if scale is not None else layout.get("dpr", 1.0))
    if origin_px is not None:
        return dpr, origin_px[0], origin_px[1]

    ox, oy = offset if offset is not None else default_viewport_offset(layout)
    return dpr, ox * dpr, oy * dpr


def dom_rect_to_frame(
    item: dict[str, Any], dpr: float, ox: float, oy: float
) -> tuple[int, int, int, int]:
    """DOM 的 {x, y, w, h}（CSS px）-> frame 像素 (x, y, w, h)。"""
    return (
        round(ox + item["x"] * dpr),
        round(oy + item["y"] * dpr),
        round(item["w"] * dpr),
        round(item["h"] * dpr),
    )