"""被蓋住的牌不算牌框：避免點到蓋在上面的按鈕（W7 實機發現的問題）。

執行方式（專案根目錄）：
    python -m tests.test_dom_visible
或
    python -m pytest tests/test_dom_visible.py -v
"""

import numpy as np

from src.control.errors import ERR_STATE_MISMATCH
from src.control.refresh import refresh_hand
from src.control.tile_mapper import TileMapper, boxes_from_dom_layout
from tests._runner import run_module

HAND = [0, 1, 2, 3, 4, 5, 9, 10, 11, 18, 19, 20, 27, 27, 31, 31, 33]
FRAME = np.zeros((1200, 1920, 3), dtype=np.uint8)


def _layout(hidden=()):
    tiles = []
    for i, tile in enumerate(sorted(HAND)):
        item = {"tile": tile, "seat": 0, "zone": "hand", "x": 100 + i * 30, "y": 600, "w": 26, "h": 40}
        if i in hidden:
            item["visible"] = False
        elif i % 2:
            item["visible"] = True  # 有的牌明確回報可見，有的沒有這個欄位（舊資料）
        tiles.append(item)
    return {"dpr": 1.0, "inner": [1000, 700], "outer": [1000, 800], "tiles": tiles}


def test_hidden_tiles_are_skipped_and_missing_flag_means_visible():
    boxes = boxes_from_dom_layout(_layout(hidden={0, 5}), seat=0)

    assert len(boxes) == 15
    assert len(boxes_from_dom_layout(_layout(), seat=0)) == 17


def test_covered_hand_becomes_state_mismatch_not_a_blind_click():
    mapper = TileMapper()
    result = refresh_hand(
        lambda: FRAME,
        lambda frame: boxes_from_dom_layout(_layout(hidden={2, 3, 4}), seat=0),
        HAND, mapper=mapper, max_attempts=2, sleep=lambda s: None,
    )

    assert not result.ok and result.error == ERR_STATE_MISMATCH
    assert len(result.check.missing) == 3
    assert mapper.tiles() == []  # 不留下可以點的牌框


if __name__ == "__main__":
    run_module(globals(), "test_dom_visible")