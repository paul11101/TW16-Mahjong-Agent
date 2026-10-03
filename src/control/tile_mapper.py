"""牌框座標映射（W3 D3）：牌 ID -> 牌框 -> 點擊座標。

座標規則（全專案統一）：
- TileBox 的 x / y / w / h 一律是「擷取畫面（frame）」的像素座標，
  也就是 ScreenCapture.grab() 回傳影像的座標，原點是擷取區域左上角。
- 只有在「真的要點擊」的那一刻，才用 window.frame_to_screen() 換成螢幕座標。
  視覺模組回傳的 bbox 本來就是 frame 座標（見 tests/test_perception_frame.py）。

牌框來源（Provider）：
- boxes_from_observation()：視覺模組 run_perception_matching() 的 Observation（真實遊戲用）。
- boxes_from_dom_layout()：測試介面網頁回報的 data-tile / data-seat 牌框（測試介面用）。
  測試介面的牌是文字，不是遊戲截圖，視覺模板比對不到，所以 W3 先用 DOM 當牌框來源。

本模組只做「查牌框、算座標、檢查」，不擷取畫面、不辨識、不決策、不點擊。
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass
from typing import Any, Iterable, Sequence

import numpy as np

from src.common.schemas import ActionType
from src.control.capture import CaptureRegion
from src.control.window import frame_to_screen

Point = tuple[int, int]


class TileMappingError(RuntimeError):
    """牌框映射失敗的共同父類別。"""


class TileNotFoundError(TileMappingError):
    """畫面上找不到要點的牌（不要盲點，應重新擷取辨識）。"""


class TileOutOfFrameError(TileMappingError):
    """牌框中心不在擷取畫面內（可能被捲動或視窗偏移）。"""


class UnsupportedActionError(TileMappingError):
    """目前只支援出牌（W4 才加反應按鈕）。"""


@dataclass(frozen=True)
class TileBox:
    """一張牌在 frame 內的位置。"""

    tile: int
    x: int
    y: int
    w: int
    h: int
    confidence: float = 1.0
    seat: int | None = None
    zone: str | None = None

    @property
    def center(self) -> Point:
        return self.x + self.w // 2, self.y + self.h // 2


@dataclass(frozen=True)
class HandCheck:
    """畫面上看到的手牌 vs 規則狀態的手牌。"""

    missing: tuple[int, ...]  # 狀態有、畫面沒看到
    extra: tuple[int, ...]  # 畫面有、狀態沒有

    @property
    def ok(self) -> bool:
        return not self.missing and not self.extra


@dataclass(frozen=True)
class ReferenceReport:
    """偵測結果 vs 對照牌框（例如 DOM）。"""

    problems: tuple[str, ...]
    max_error: float  # 像素

    @property
    def ok(self) -> bool:
        return not self.problems


@dataclass(frozen=True)
class ClickPlan:
    """一次出牌點擊的計畫；frame_point 與 screen_point 都先算好，方便記錄。"""

    action_id: str
    tile: int
    box: TileBox
    frame_point: Point
    screen_point: Point


def _sorted(boxes: Iterable[TileBox]) -> list[TileBox]:
    return sorted(boxes, key=lambda b: (b.x, b.y))


# ---------------------------------------------------------------- Provider

def boxes_from_observation(
    observation: dict[str, Any], *, min_confidence: float = 0.0
) -> list[TileBox]:
    """視覺 Observation -> TileBox（座標已是 frame 座標，不轉換）。

    card 不是 0~41 的整數、或信心低於門檻的項目會略過。
    """
    boxes: list[TileBox] = []
    for item in observation.get("detected_cards", []):
        try:
            tile = int(item["card"])
            x, y, w, h = (int(round(v)) for v in item["bbox"])
        except (KeyError, TypeError, ValueError):
            continue

        confidence = float(item.get("confidence", 0.0))
        if not 0 <= tile <= 41 or confidence < min_confidence:
            continue

        boxes.append(TileBox(tile, x, y, w, h, confidence=confidence, zone="hand"))

    return _sorted(boxes)


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


# 測試介面左上角的洋紅色校正標記（table_page.py 的 #calib），寬高為 CSS px
CALIB_CSS_SIZE = 8


def find_calibration_marker(
    frame: np.ndarray, *, search_size: int = 600
) -> tuple[int, int, int, int] | None:
    """在 frame 左上角找洋紅色校正標記，回傳 (x, y, w, h)（frame 像素）；找不到回傳 None。

    標記固定在網頁可視區的左上角 (0, 0)，所以它的左上角就是「網頁可視區原點」
    在 frame 內的精確位置，不需要猜瀏覽器邊框／標題列大小。
    """
    if frame is None or frame.ndim != 3 or frame.shape[2] < 3:
        return None

    sub = frame[:search_size, :search_size]
    mask = (sub[:, :, 0] > 200) & (sub[:, :, 1] < 60) & (sub[:, :, 2] > 200)  # BGR 洋紅
    ys, xs = np.nonzero(mask)
    if xs.size == 0:
        return None

    x0, x1 = int(xs.min()), int(xs.max())
    y0, y1 = int(ys.min()), int(ys.max())
    return x0, y0, x1 - x0 + 1, y1 - y0 + 1


def boxes_from_dom_layout(
    layout: dict[str, Any],
    *,
    seat: int,
    zone: str | None = "hand",
    offset: tuple[float, float] | None = None,
    scale: float | None = None,
    origin_px: tuple[float, float] | None = None,
) -> list[TileBox]:
    """測試介面 /api/layout 的 DOM 牌框 -> frame 座標 TileBox。

    DOM 的 getBoundingClientRect 是「CSS px、相對網頁可視區」，
    換成 frame 像素：(x + 可視區偏移) * devicePixelRatio。

    seat / zone 對應 DOM 的 data-seat / data-zone（zone：hand / river / meld / flower）。

    可視區原點的來源，優先順序：
    1. origin_px：frame 像素，通常來自 find_calibration_marker()，最準。
    2. offset：手動指定（CSS px）。
    3. 都沒給：用 default_viewport_offset() 估計（非最大化視窗會有誤差）。
    """
    dpr = float(scale if scale is not None else layout.get("dpr", 1.0))
    if origin_px is not None:
        ox_px, oy_px = origin_px
    else:
        ox, oy = offset if offset is not None else default_viewport_offset(layout)
        ox_px, oy_px = ox * dpr, oy * dpr

    boxes: list[TileBox] = []
    for t in layout.get("tiles", []):
        if t.get("seat") != seat:
            continue
        if zone is not None and t.get("zone") != zone:
            continue

        boxes.append(
            TileBox(
                tile=int(t["tile"]),
                x=round(ox_px + t["x"] * dpr),
                y=round(oy_px + t["y"] * dpr),
                w=round(t["w"] * dpr),
                h=round(t["h"] * dpr),
                seat=seat,
                zone=t.get("zone"),
            )
        )

    return _sorted(boxes)


# ------------------------------------------------------------------ Mapper

class TileMapper:
    """保存「最新一幀」的手牌牌框，提供查詢與檢查。

    每次重新擷取後呼叫 update()；舊牌框不保留（狀態過期要重新決策）。
    """

    def __init__(self, frame_size: tuple[int, int] | None = None) -> None:
        self.frame_size = frame_size  # (寬, 高)
        self._boxes: tuple[TileBox, ...] = ()

    def update(
        self, boxes: Iterable[TileBox], *, frame_size: tuple[int, int] | None = None
    ) -> None:
        if frame_size is not None:
            self.frame_size = frame_size
        self._boxes = tuple(_sorted(boxes))

    @property
    def boxes(self) -> tuple[TileBox, ...]:
        return self._boxes

    def tiles(self) -> list[int]:
        """由左到右的牌 ID。"""
        return [b.tile for b in self._boxes]

    def find(self, tile: int, *, occurrence: int = 0) -> TileBox:
        """找某張牌的牌框。

        相同牌有多張時，occurrence 指定第幾張（由左到右，0 起算；-1 是最右邊）。
        出牌時相同牌任選一張都等價，預設取最左邊。
        """
        matches = [b for b in self._boxes if b.tile == tile]
        if not matches:
            raise TileNotFoundError(f"畫面上找不到牌 {tile}")

        try:
            box = matches[occurrence]
        except IndexError:
            raise TileNotFoundError(
                f"牌 {tile} 只有 {len(matches)} 張，要求第 {occurrence} 張"
            ) from None

        self._ensure_inside(box)
        return box

    def frame_point(self, tile: int, *, occurrence: int = 0) -> Point:
        """牌框中心（frame 座標）。"""
        return self.find(tile, occurrence=occurrence).center

    def screen_point(
        self, tile: int, region: CaptureRegion, *, occurrence: int = 0
    ) -> Point:
        """牌框中心（螢幕座標，點擊用）。region 是這一幀的擷取區域。"""
        return frame_to_screen(region, *self.frame_point(tile, occurrence=occurrence))

    def check_hand(self, expected_hand: Iterable[int]) -> HandCheck:
        """畫面上的牌 vs 規則狀態的手牌（多重集合比較）。"""
        expected = Counter(expected_hand)
        seen = Counter(self.tiles())
        return HandCheck(
            missing=tuple(sorted((expected - seen).elements())),
            extra=tuple(sorted((seen - expected).elements())),
        )

    def _ensure_inside(self, box: TileBox) -> None:
        if self.frame_size is None:
            return

        width, height = self.frame_size
        cx, cy = box.center
        if not (0 <= cx < width and 0 <= cy < height):
            raise TileOutOfFrameError(
                f"牌 {box.tile} 的中心 {box.center} 不在畫面 {width}x{height} 內"
            )


# --------------------------------------------------------------- 對照 / 決策

def compare_with_reference(
    detected: Sequence[TileBox],
    reference: Sequence[TileBox],
    *,
    tolerance: float = 8.0,
) -> ReferenceReport:
    """把偵測牌框與對照牌框（例如 DOM）逐張比對：同牌 ID、中心距離在容許像素內。"""
    pool: dict[int, list[TileBox]] = {}
    for box in detected:
        pool.setdefault(box.tile, []).append(box)

    problems: list[str] = []
    max_error = 0.0

    for ref in reference:
        candidates = pool.get(ref.tile, [])
        if not candidates:
            problems.append(f"牌 {ref.tile}：偵測不到（對照位置 {ref.center}）")
            continue

        best = min(candidates, key=lambda b: math.dist(b.center, ref.center))
        candidates.remove(best)

        error = math.dist(best.center, ref.center)
        max_error = max(max_error, error)
        if error > tolerance:
            problems.append(
                f"牌 {ref.tile}：位置誤差 {error:.1f}px > {tolerance}px"
                f"（偵測 {best.center}，對照 {ref.center}）"
            )

    for tile, rest in pool.items():
        for box in rest:
            problems.append(f"牌 {tile}：多偵測到一張 {box.center}")

    return ReferenceReport(problems=tuple(problems), max_error=max_error)


def plan_discard_click(
    decision: Any,
    mapper: TileMapper,
    region: CaptureRegion,
    *,
    occurrence: int = 0,
) -> ClickPlan:
    """策略 Decision（出牌）-> 點擊計畫。

    decision 是 src.strategy.interfaces.Decision（用 decision.action.action / .tile / .id）。
    只計算座標，不點擊；點擊與 ActionReceipt 是 W3 D4。
    """
    action = decision.action
    if ActionType(action.action) != ActionType.DISCARD or action.tile is None:
        raise UnsupportedActionError(f"目前只支援出牌，收到 {action.id}")

    box = mapper.find(action.tile, occurrence=occurrence)
    frame_point = box.center

    return ClickPlan(
        action_id=action.id,
        tile=action.tile,
        box=box,
        frame_point=frame_point,
        screen_point=frame_to_screen(region, *frame_point),
    )