"""W3 D3 牌框座標映射測試（合成資料，不需要瀏覽器或真實截圖）。

執行方式（專案根目錄）：
    python -m tests.test_tile_mapper
或
    python -m pytest tests/test_tile_mapper.py -v
"""

import numpy as np

from src.common.schemas import ActionType
from src.control.capture import CaptureRegion
from src.control.tile_mapper import (
    TileBox,
    TileMapper,
    TileNotFoundError,
    TileOutOfFrameError,
    UnsupportedActionError,
    boxes_from_dom_layout,
    boxes_from_observation,
    compare_with_reference,
    find_calibration_marker,
    plan_discard_click,
)
from src.control.window import frame_to_screen
from src.rules.legal_actions import LegalActionGenerator
from src.strategy.adapters import actions_to_legal_actions, game_state_to_observation
from src.strategy.baseline import BaselinePolicy
from src.strategy.interfaces import Decision, LegalAction
from test_interface.agent_runner import SEAT, make_fake_game_state

# 合成畫面：dpr 1.5，outer 1280x800、inner 1264x700
# -> 可視區偏移 = (8, 92) CSS px；frame = outer * dpr = 1920x1200
REGION = CaptureRegion(100, 50, 1920, 1200)
FRAME_SIZE = (1920, 1200)


def _raises(exc_type, fn):
    try:
        fn()
    except exc_type:
        return
    raise AssertionError(f"應該拋出 {exc_type.__name__}")


def make_layout(hand):
    tiles = []
    for i, t in enumerate(sorted(hand)):
        tiles.append({"tile": t, "seat": 0, "zone": "hand", "x": 100 + i * 30, "y": 600, "w": 26, "h": 40})
    tiles.append({"tile": 29, "seat": 0, "zone": "river", "x": 300, "y": 300, "w": 22, "h": 34})
    tiles.append({"tile": 5, "seat": 1, "zone": "river", "x": 700, "y": 200, "w": 22, "h": 34})
    return {"dpr": 1.5, "inner": [1264, 700], "outer": [1280, 800], "tiles": tiles}


def _hand():
    return list(make_fake_game_state("t").players[SEAT].hand)


def _mapper():
    mapper = TileMapper(frame_size=FRAME_SIZE)
    mapper.update(boxes_from_dom_layout(make_layout(_hand()), seat=SEAT))
    return mapper


def test_dom_layout_to_frame_boxes():
    boxes = boxes_from_dom_layout(make_layout(_hand()), seat=SEAT)

    assert len(boxes) == 17
    # x: (100+8)*1.5=162  y: (600+92)*1.5=1038  w: 26*1.5=39  h: 40*1.5=60
    assert boxes[0] == TileBox(0, 162, 1038, 39, 60, seat=0, zone="hand")
    assert boxes[0].center == (181, 1068)
    assert boxes[1].x == 207  # (130+8)*1.5


def test_dom_layout_filters_seat_and_zone():
    layout = make_layout(_hand())

    assert all(b.zone == "hand" and b.seat == 0 for b in boxes_from_dom_layout(layout, seat=0))
    assert [b.tile for b in boxes_from_dom_layout(layout, seat=0, zone="river")] == [29]
    assert boxes_from_dom_layout(layout, seat=1) == []  # 他家沒有手牌牌框
    assert len(boxes_from_dom_layout(layout, seat=0, zone=None)) == 18


def test_offset_and_scale_override():
    box = boxes_from_dom_layout(make_layout(_hand()), seat=0, offset=(0, 0), scale=1.0)[0]
    assert (box.x, box.y, box.w, box.h) == (100, 600, 26, 40)


def test_observation_to_boxes():
    obs = {
        "window_size": [1920, 1200],
        "detected_cards": [
            {"card": "5", "bbox": [300, 1000, 40, 60], "confidence": 0.9},
            {"card": "3", "bbox": [100, 1000, 40, 60], "confidence": 0.95},
            {"card": "oops", "bbox": [200, 1000, 40, 60], "confidence": 0.9},
            {"card": "7", "bbox": [500, 1000, 40, 60], "confidence": 0.3},
        ],
    }
    boxes = boxes_from_observation(obs, min_confidence=0.6)

    assert [b.tile for b in boxes] == [3, 5]  # 由左到右、略過非數字與低信心
    assert boxes[0].center == (120, 1030)


def test_duplicate_tiles_and_missing_tile():
    mapper = _mapper()

    assert mapper.tiles() == sorted(_hand())
    assert mapper.find(27, occurrence=0).x < mapper.find(27, occurrence=-1).x
    _raises(TileNotFoundError, lambda: mapper.find(27, occurrence=2))
    _raises(TileNotFoundError, lambda: mapper.find(40))


def test_check_hand():
    mapper = _mapper()
    hand = _hand()

    assert mapper.check_hand(hand).ok
    assert mapper.check_hand(hand + [7]).missing == (7,)
    assert mapper.check_hand(hand[:-1]).extra == (33,)


def test_out_of_frame_rejected():
    mapper = TileMapper(frame_size=(100, 100))
    mapper.update(boxes_from_dom_layout(make_layout(_hand()), seat=SEAT))
    _raises(TileOutOfFrameError, lambda: mapper.find(0))


def test_baseline_decision_to_screen_click():
    state = make_fake_game_state("t")
    hand = list(state.players[SEAT].hand)
    observation = game_state_to_observation(state, seat=SEAT)
    legal = actions_to_legal_actions(LegalActionGenerator().get_turn_player_actions(hand=hand))
    decision = BaselinePolicy().decide(observation, legal)

    plan = plan_discard_click(decision, _mapper(), REGION)

    assert plan.tile == 0 and plan.action_id == "discard_0"
    assert plan.frame_point == (181, 1068)  # frame 座標
    assert plan.screen_point == frame_to_screen(REGION, 181, 1068) == (281, 1118)  # 螢幕座標


def test_non_discard_decision_rejected():
    decision = Decision(
        action=LegalAction(id="win_1", action=ActionType.WIN, tile=1),
        score=1.0,
        reason="test",
    )
    _raises(UnsupportedActionError, lambda: plan_discard_click(decision, _mapper(), REGION))


def test_compare_with_reference():
    reference = boxes_from_dom_layout(make_layout(_hand()), seat=SEAT)

    shifted = [TileBox(b.tile, b.x + 3, b.y, b.w, b.h) for b in reference]
    report = compare_with_reference(shifted, reference)
    assert report.ok and abs(report.max_error - 3.0) < 1e-6

    far = [TileBox(b.tile, b.x + 20, b.y, b.w, b.h) for b in reference]
    assert not compare_with_reference(far, reference).ok

    missing = compare_with_reference(reference[1:], reference)
    assert not missing.ok and "偵測不到" in missing.problems[0]


def test_find_calibration_marker():
    frame = np.zeros((1200, 1920, 3), dtype=np.uint8)
    assert find_calibration_marker(frame) is None  # 沒有標記

    frame[91:107, 37:53] = (255, 0, 255)  # BGR 洋紅，16x16（8 CSS px * dpr 2）
    assert find_calibration_marker(frame) == (37, 91, 16, 16)

    # 非連續陣列（ScreenCapture.grab() 去掉 alpha 後）也能用
    bgra = np.dstack([frame, np.full(frame.shape[:2], 255, dtype=np.uint8)])
    assert find_calibration_marker(bgra[:, :, :3]) == (37, 91, 16, 16)


def test_dom_boxes_use_marker_origin():
    layout = make_layout(_hand())

    # 可視區原點在 frame 的 (37, 91)；dpr 1.5：x = 37 + 100*1.5，y = 91 + 600*1.5
    box = boxes_from_dom_layout(layout, seat=SEAT, origin_px=(37, 91))[0]
    assert (box.x, box.y, box.w, box.h) == (187, 991, 39, 60)

    # 有給 origin_px 時，不再使用 inner/outer 的估計值
    layout["inner"], layout["outer"] = [1, 1], [999, 999]
    assert boxes_from_dom_layout(layout, seat=SEAT, origin_px=(37, 91))[0].x == 187


if __name__ == "__main__":
    test_dom_layout_to_frame_boxes()
    test_dom_layout_filters_seat_and_zone()
    test_offset_and_scale_override()
    test_observation_to_boxes()
    test_duplicate_tiles_and_missing_tile()
    test_check_hand()
    test_out_of_frame_rejected()
    test_baseline_decision_to_screen_click()
    test_non_discard_decision_rejected()
    test_compare_with_reference()
    test_find_calibration_marker()
    test_dom_boxes_use_marker_origin()
    print("✅ test_tile_mapper：12 項測試全部通過")