"""W5 D3/D4 重新擷取、低信心處理、狀態重建測試（合成畫面，不需要瀏覽器）。

執行方式（專案根目錄）：
    python -m tests.test_refresh
或
    python -m pytest tests/test_refresh.py -v
"""

import numpy as np
import pytest

from src.control.errors import ERR_CAPTURE_FAILED, ERR_LOW_CONFIDENCE, ERR_STATE_MISMATCH
from src.control.refresh import (
    RefreshResult,
    rebuild_from_refresh,
    rebuild_own_hand,
    refresh_hand,
)
from src.control.tile_mapper import TileBox, TileMapper
from test_interface.agent_runner import SEAT, make_fake_game_state
from tests._runner import run_module

HAND = [0, 1, 2, 3, 4, 5, 9, 10, 11, 18, 19, 20, 27, 27, 31, 31, 33]
FRAME = np.zeros((1200, 1920, 3), dtype=np.uint8)


def boxes_for(hand, conf=0.95, low_index=None):
    boxes = []
    for i, tile in enumerate(sorted(hand)):
        c = 0.3 if i == low_index else conf
        boxes.append(TileBox(tile, 100 + i * 30, 600, 26, 40, confidence=c))
    return boxes


def sequence_world(box_lists, *, frames=None):
    """依序回傳 box_lists；capture 依序回傳 frames（預設都是 FRAME）。"""
    state = {"cap": 0, "box": 0}
    frames = frames or [FRAME] * len(box_lists)

    def capture():
        i = min(state["cap"], len(frames) - 1)
        state["cap"] += 1
        return frames[i]

    def boxes_fn(_frame):
        i = min(state["box"], len(box_lists) - 1)
        state["box"] += 1
        return box_lists[i]

    return capture, boxes_fn, state


def _run(box_lists, mapper=None, **kw):
    capture, boxes_fn, state = sequence_world(box_lists, frames=kw.pop("frames", None))
    sleeps = []
    result = refresh_hand(
        capture, boxes_fn, HAND, mapper=mapper, sleep=sleeps.append, **kw
    )
    return result, sleeps, state


def test_first_attempt_ok_updates_mapper():
    mapper = TileMapper()
    result, sleeps, _ = _run([boxes_for(HAND)], mapper)

    assert result.ok and result.attempts == 1 and result.error is None
    assert sleeps == []
    assert mapper.tiles() == sorted(HAND)
    assert mapper.frame_size == (1920, 1200)


def test_low_confidence_retakes_then_ok():
    mapper = TileMapper()
    result, sleeps, state = _run([boxes_for(HAND, low_index=3), boxes_for(HAND)], mapper, retry_delay=0.2)

    assert result.ok and result.attempts == 2
    assert sleeps == [0.2]
    assert state["cap"] == 2
    assert [d["result"] for d in result.attempt_log] == ["low_confidence", "ok"]
    assert mapper.tiles() == sorted(HAND)


def test_low_confidence_every_time_fails_and_clears_mapper():
    mapper = TileMapper(frame_size=(1920, 1200))
    mapper.update(boxes_for(HAND))  # 舊牌框
    result, sleeps, _ = _run([boxes_for(HAND, low_index=0)], mapper, max_attempts=3)

    assert not result.ok and result.attempts == 3
    assert result.error == ERR_LOW_CONFIDENCE
    assert len(result.low_confidence) == 1
    assert len(sleeps) == 2  # 最後一次失敗後不用再等
    assert mapper.tiles() == []  # 舊牌框已清掉，不會點到過期位置


def test_mismatch_then_ok():
    wrong = boxes_for([t for t in HAND if t != 33] + [7])
    result, _, _ = _run([wrong, boxes_for(HAND)])

    assert result.ok and result.attempts == 2
    assert [d["result"] for d in result.attempt_log] == ["mismatch", "ok"]


def test_mismatch_every_time_reports_check():
    wrong = boxes_for(HAND[:-2])
    result, _, _ = _run([wrong], max_attempts=2)

    assert not result.ok and result.error == ERR_STATE_MISMATCH
    assert result.check is not None and result.check.missing == (31, 33)
    assert len(result.boxes) == 15


def test_capture_failure_returns_immediately():
    mapper = TileMapper()
    mapper.update(boxes_for(HAND))
    result = refresh_hand(lambda: None, lambda f: [], HAND, mapper=mapper, sleep=lambda s: None)

    assert not result.ok and result.error == ERR_CAPTURE_FAILED and result.attempts == 1
    assert mapper.tiles() == []


def test_meld_count_is_passed_to_check():
    hand13 = HAND[:13]
    capture, boxes_fn, _ = sequence_world([boxes_for(hand13)])

    result = refresh_hand(capture, boxes_fn, hand13, meld_count=1, sleep=lambda s: None)
    assert result.ok


def test_max_attempts_must_be_positive():
    with pytest.raises(ValueError):
        refresh_hand(lambda: FRAME, lambda f: [], HAND, max_attempts=0)


# ------------------------------------------------------------ 狀態重建

def test_rebuild_own_hand_returns_copy_with_diff():
    state = make_fake_game_state("t_rebuild")
    visible = [t for t in state.players[SEAT].hand if t != 33] + [7]

    rebuilt = rebuild_own_hand(state, SEAT, visible)

    assert rebuilt.changed
    assert rebuilt.added == (7,) and rebuilt.removed == (33,)
    assert rebuilt.state.players[SEAT].hand == visible
    assert 33 in state.players[SEAT].hand  # 原物件沒被改
    assert rebuilt.state is not state


def test_rebuild_same_hand_is_unchanged():
    state = make_fake_game_state("t_same")
    rebuilt = rebuild_own_hand(state, SEAT, list(state.players[SEAT].hand))

    assert not rebuilt.changed and rebuilt.added == () and rebuilt.removed == ()


def test_rebuild_unknown_seat_raises():
    with pytest.raises(ValueError):
        rebuild_own_hand(make_fake_game_state("t"), 9, [])


def test_rebuild_from_refresh_only_accepts_ok_result():
    state = make_fake_game_state("t_ref")
    bad = RefreshResult(False, (), 3, ERR_LOW_CONFIDENCE)
    with pytest.raises(ValueError):
        rebuild_from_refresh(state, SEAT, bad)

    good = RefreshResult(True, tuple(boxes_for(HAND)), 1)
    assert not rebuild_from_refresh(state, SEAT, good).changed


if __name__ == "__main__":
    run_module(globals(), "test_refresh")