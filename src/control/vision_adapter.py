"""視覺接入（W8）：把 perception/detector.py 的輸出轉成整合端用的格式。

視覺已定案只用 MahjongDetector.detect_full_state()。本模組只做「轉接」，不改視覺的程式：

1. normalize_frame()：detector 的模板是 3543x1981 畫面裁切的，且只做「同比例縮小加速」，
   沒有針對解析度調整模板大小。所以整合端先把畫面縮放到 detector.base_height 高再丟進去，
   回傳的 bbox 再乘回比例，換回「真實 frame 座標」（TileBox 一律是 frame 座標）。
2. DetectorVision.hand_boxes(frame)：可直接當 refresh_hand / prepare_turn 的 boxes_fn。
3. VisionObserver.snapshot()：給 GameRunner 用的觀察器，階段由畫面推出
   （結算 -> over、動畫中 -> waiting、有輪到自己指示且手牌張數正確 -> my_turn、有按鈕 -> reaction）。

不做：模板比對、決策、點擊。
"""

from __future__ import annotations

from typing import Any, Callable, Sequence

import numpy as np

from src.control.button_mapper import ButtonBox
from src.control.game_profile import HAND_MY_TURN, ITAIWANMJ16, classify_hand
from src.control.game_runner import (
    PHASE_MY_TURN,
    PHASE_OVER,
    PHASE_REACTION,
    PHASE_WAITING,
    Snapshot,
)
from src.control.tile_mapper import TileBox

DEFAULT_BASE_HEIGHT = 1980.0

# 按鈕模板名稱 -> 動作；依序比對（小寫、去掉 btn_ 前綴後做「包含」比對）。
# 模板實際檔名由視覺決定，請對照 data/samples 內的 btn_*.png 確認。
BUTTON_KEYWORDS: tuple[tuple[str, str], ...] = (
    ("chi", "chi"), ("吃", "chi"),
    ("pong", "pong"), ("peng", "pong"), ("碰", "pong"),
    ("kong", "kong"), ("gang", "kong"), ("槓", "kong"),
    ("win", "win"), ("胡", "win"), ("hu", "win"),
    ("pass", "pass"), ("guo", "pass"), ("過", "pass"),
)


def button_action(name: str) -> str | None:
    """模板名稱 -> chi/pong/kong/win/pass；認不得回傳 None。"""
    text = str(name).lower()
    if text.startswith("btn_"):
        text = text[4:]
    for keyword, action in BUTTON_KEYWORDS:
        if keyword in text:
            return action
    return None


def normalize_frame(frame: np.ndarray, base_height: float = DEFAULT_BASE_HEIGHT) -> tuple[np.ndarray, float]:
    """把畫面縮放到 base_height 高。回傳 (縮放後畫面, 回推係數)；bbox * 係數 = 真實 frame 座標。"""
    image = np.ascontiguousarray(frame)
    height, width = image.shape[:2]
    target = int(round(base_height))
    if abs(height - target) <= 1:
        return image, 1.0

    import cv2

    factor = target / height
    interpolation = cv2.INTER_AREA if factor < 1 else cv2.INTER_LINEAR
    resized = cv2.resize(image, (int(round(width * factor)), target), interpolation=interpolation)
    return resized, height / target


def _scaled_bbox(bbox: Sequence[float], back: float) -> tuple[int, int, int, int]:
    x, y, w, h = bbox
    return round(x * back), round(y * back), round(w * back), round(h * back)


def boxes_from_cards(
    cards: Sequence[dict[str, Any]],
    back: float = 1.0,
    *,
    zone: str = "hand",
    margin_as_low: bool = True,
    low_conf_value: float = 0.5,
) -> list[TileBox]:
    """detector 的牌清單 -> TileBox（由左到右）。

    name 不是 0~41 的整數就略過。margin_as_low：detector 標記 low_confidence（第一名與第二名太接近）
    的牌，信心壓到 low_conf_value，refresh_hand 會把它當低信心重拍，不會盲點。
    """
    boxes: list[TileBox] = []
    for card in cards:
        try:
            tile = int(card["name"])
            x, y, w, h = _scaled_bbox(card["bbox"], back)
        except (KeyError, TypeError, ValueError):
            continue
        if not 0 <= tile <= 41:
            continue

        confidence = float(card.get("confidence", 0.0))
        if margin_as_low and card.get("low_confidence"):
            confidence = min(confidence, low_conf_value)
        boxes.append(TileBox(tile, x, y, w, h, confidence=confidence, zone=zone))

    return sorted(boxes, key=lambda b: (b.x, b.y))


def boxes_from_buttons(buttons: Sequence[dict[str, Any]], back: float = 1.0) -> list[ButtonBox]:
    """detector 的 action_buttons -> ButtonBox。detector 沒有「可不可點」資訊，一律視為可點。"""
    out: list[ButtonBox] = []
    for item in buttons:
        action = button_action(item.get("name", ""))
        if action is None:
            continue
        try:
            x, y, w, h = _scaled_bbox(item["bbox"], back)
        except (KeyError, TypeError, ValueError):
            continue
        out.append(ButtonBox(action, x, y, w, h, enabled=True))
    return out


class DetectorVision:
    """包住 MahjongDetector：每次呼叫都先正規化畫面，再把結果換回真實座標。"""

    def __init__(
        self,
        detector: Any,
        *,
        base_height: float | None = None,
        scan_buttons: bool = False,
        margin_as_low: bool = True,
    ) -> None:
        self.detector = detector
        self.base_height = float(base_height or getattr(detector, "base_height", DEFAULT_BASE_HEIGHT))
        self.scan_buttons = scan_buttons  # True 會一併掃河牌／副露／按鈕（detector 目前綁在一起，較慢）
        self.margin_as_low = margin_as_low
        self.last_state: dict[str, Any] = {}
        self.last_back: float = 1.0

    def detect(self, frame: np.ndarray) -> dict[str, Any]:
        image, back = normalize_frame(frame, self.base_height)
        state = self.detector.detect_full_state(image, scan_secondary_rois=self.scan_buttons) or {}
        self.last_state, self.last_back = state, back
        return state

    def hand_boxes(self, frame: np.ndarray) -> list[TileBox]:
        """boxes_fn：refresh_hand / prepare_turn 直接使用。"""
        state = self.detect(frame)
        return boxes_from_cards(state.get("hand_cards", []), self.last_back, margin_as_low=self.margin_as_low)

    def flower_boxes(self) -> list[TileBox]:
        return boxes_from_cards(
            self.last_state.get("flower_cards", []), self.last_back, zone="flower", margin_as_low=False
        )

    def button_boxes(self) -> list[ButtonBox]:
        return boxes_from_buttons(self.last_state.get("action_buttons", []), self.last_back)


class VisionObserver:
    """GameRunner 的 observe_fn：只讀畫面（不讀測試後端）。"""

    def __init__(
        self,
        capture_fn: Callable[[], Any],
        vision: DetectorVision,
        *,
        meld_count_fn: Callable[[], int] | None = None,
        require_turn_indicator: bool = True,
        hand_size: int = ITAIWANMJ16.hand_size,
    ) -> None:
        self.capture_fn = capture_fn
        self.vision = vision
        self.meld_count_fn = meld_count_fn
        self.require_turn_indicator = require_turn_indicator
        self.hand_size = hand_size

    def snapshot(self) -> Snapshot | None:
        frame = self.capture_fn()
        if frame is None:
            return None

        state = self.vision.detect(frame)
        if not state:
            return None

        boxes = boxes_from_cards(state.get("hand_cards", []), self.vision.last_back, margin_as_low=False)
        tiles = [b.tile for b in boxes]
        actions = sorted({b.action for b in self.vision.button_boxes()})
        melds = self.meld_count_fn() if self.meld_count_fn else 0
        status = classify_hand(tiles, hand_size=self.hand_size, meld_count=melds)

        my_turn = bool(state.get("is_my_turn")) or not self.require_turn_indicator
        if state.get("in_settlement"):
            phase = PHASE_OVER
        elif state.get("is_animating"):
            phase = PHASE_WAITING  # 動畫中不動作
        elif my_turn and status == HAND_MY_TURN:
            phase = PHASE_MY_TURN
        elif actions:
            phase = PHASE_REACTION
        else:
            phase = PHASE_WAITING

        return Snapshot(
            phase=phase,
            fingerprint=(phase, tuple(sorted(tiles)), tuple(actions)),
            detail={
                "hand_count": len(tiles),
                "hand_status": status,
                "is_my_turn": bool(state.get("is_my_turn")),
                "buttons": actions,
                "stable": bool((state.get("verification") or {}).get("is_stable", True)),
            },
            data=state,
        )