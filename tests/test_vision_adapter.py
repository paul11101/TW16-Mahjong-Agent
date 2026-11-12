"""W8 視覺接入轉接層測試：假 detector、合成畫面，不需要 data/samples 或視窗。

執行方式（專案根目錄）：
    python -m tests.test_vision_adapter
或
    python -m pytest tests/test_vision_adapter.py -v
"""

import numpy as np

from src.control.game_runner import PHASE_MY_TURN, PHASE_OVER, PHASE_REACTION, PHASE_WAITING
from src.control.refresh import refresh_hand
from src.control.tile_mapper import TileMapper
from src.control.vision_adapter import (
    DetectorVision,
    VisionObserver,
    boxes_from_buttons,
    boxes_from_cards,
    button_action,
    normalize_frame,
)
from tests._runner import run_module

HAND = [0, 1, 2, 3, 4, 5, 9, 10, 11, 18, 19, 20, 27, 27, 31, 31, 33]  # 17 張


def cards(tiles, *, low=()):
    return [
        {"name": str(t), "bbox": (100 + i * 150, 1500, 100, 140), "confidence": 0.95,
         "margin": 0.2, "low_confidence": i in low}
        for i, t in enumerate(sorted(tiles))
    ]


class FakeDetector:
    base_height = 1980.0

    def __init__(self, **state):
        self.state = state
        self.shapes = []
        self.scan_flags = []

    def detect_full_state(self, image, scan_secondary_rois=False):
        self.shapes.append(image.shape[:2])
        self.scan_flags.append(scan_secondary_rois)
        return self.state


def frame(h=1618, w=2880):
    return np.zeros((h, w, 3), dtype=np.uint8)


def test_normalize_frame_scales_and_returns_back_factor():
    image, back = normalize_frame(frame(1618, 2880), 1980.0)
    assert image.shape[0] == 1980 and image.shape[1] == round(2880 * 1980 / 1618)
    assert abs(back - 1618 / 1980) < 1e-9

    same, back1 = normalize_frame(frame(1980, 3543), 1980.0)
    assert same.shape[:2] == (1980, 3543) and back1 == 1.0


def test_hand_boxes_are_mapped_back_to_real_frame():
    det = FakeDetector(hand_cards=cards(HAND))
    vision = DetectorVision(det)
    boxes = vision.hand_boxes(frame(1618, 2880))

    assert det.shapes[0][0] == 1980  # detector 看到的是正規化後的畫面
    assert len(boxes) == 17 and [b.tile for b in boxes] == sorted(HAND)
    back = 1618 / 1980
    first = boxes[0]
    assert (first.x, first.y) == (round(100 * back), round(1500 * back))
    assert (first.w, first.h) == (round(100 * back), round(140 * back))
    assert first.zone == "hand" and first.confidence == 0.95


def test_native_resolution_is_not_resized():
    det = FakeDetector(hand_cards=cards(HAND))
    boxes = DetectorVision(det).hand_boxes(frame(1980, 3543))

    assert det.shapes[0] == (1980, 3543) and boxes[0].x == 100


def test_low_confidence_and_bad_names():
    raw = cards(HAND[:3], low={1}) + [{"name": "ready", "bbox": (1, 2, 3, 4), "confidence": 0.9}]
    boxes = boxes_from_cards(raw)

    assert len(boxes) == 3  # 非數字名稱略過
    assert [b.confidence for b in boxes] == [0.95, 0.5, 0.95]
    assert boxes_from_cards(raw, margin_as_low=False)[1].confidence == 0.95


def test_button_mapping():
    assert button_action("btn_chi") == "chi" and button_action("btn_peng") == "pong"
    assert button_action("btn_pass") == "pass" and button_action("btn_unknown") is None
    out = boxes_from_buttons([
        {"name": "btn_win", "bbox": (10, 20, 30, 40)},
        {"name": "btn_zzz", "bbox": (1, 1, 1, 1)},
    ], back=0.5)
    assert len(out) == 1 and out[0].action == "win" and (out[0].x, out[0].w) == (5, 15)


def test_refresh_hand_accepts_vision_boxes_fn():
    vision = DetectorVision(FakeDetector(hand_cards=cards(HAND)))
    mapper = TileMapper()
    result = refresh_hand(lambda: frame(), vision.hand_boxes, HAND, mapper=mapper, sleep=lambda s: None)

    assert result.ok and mapper.tiles() == sorted(HAND)


def test_refresh_hand_retakes_on_low_margin():
    vision = DetectorVision(FakeDetector(hand_cards=cards(HAND, low={2})))
    result = refresh_hand(lambda: frame(), vision.hand_boxes, HAND, max_attempts=2, sleep=lambda s: None)

    assert not result.ok and result.error == "LOW_CONFIDENCE"


def _observer(**state):
    vision = DetectorVision(FakeDetector(**state))
    return VisionObserver(lambda: frame(), vision)


def test_phases():
    base = dict(hand_cards=cards(HAND), is_my_turn=True, is_animating=False, in_settlement=False)

    my = _observer(**base).snapshot()
    assert my.phase == PHASE_MY_TURN and my.detail["hand_count"] == 17

    assert _observer(**{**base, "is_my_turn": False}).snapshot().phase == PHASE_WAITING
    assert _observer(**{**base, "hand_cards": cards(HAND[:16])}).snapshot().phase == PHASE_WAITING
    assert _observer(**{**base, "is_animating": True}).snapshot().phase == PHASE_WAITING
    assert _observer(**{**base, "in_settlement": True}).snapshot().phase == PHASE_OVER

    reaction = _observer(
        **{**base, "is_my_turn": False, "hand_cards": cards(HAND[:16]),
           "action_buttons": [{"name": "btn_pass", "bbox": (1, 1, 5, 5)}]}
    ).snapshot()
    assert reaction.phase == PHASE_REACTION and reaction.detail["buttons"] == ["pass"]


def test_fingerprint_changes_when_hand_changes_and_capture_failure():
    a = _observer(hand_cards=cards(HAND), is_my_turn=True).snapshot()
    b = _observer(hand_cards=cards(HAND[1:] + [7]), is_my_turn=True).snapshot()
    assert a.fingerprint != b.fingerprint

    vision = DetectorVision(FakeDetector(hand_cards=cards(HAND)))
    assert VisionObserver(lambda: None, vision).snapshot() is None
    assert VisionObserver(lambda: frame(), DetectorVision(FakeDetector())).snapshot() is None


def test_scan_buttons_flag_is_forwarded():
    det = FakeDetector(hand_cards=[])
    DetectorVision(det, scan_buttons=True).detect(frame())
    DetectorVision(det).detect(frame())
    assert det.scan_flags == [True, False]


if __name__ == "__main__":
    run_module(globals(), "test_vision_adapter")