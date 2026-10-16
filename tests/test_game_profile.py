"""正式遊戲接入的整合輔助測試（不需要瀏覽器、視窗或視覺模板）。

執行方式（專案根目錄）：
    python -m tests.test_game_profile
或
    python -m pytest tests/test_game_profile.py -v
"""

import pytest

from src.control.capture import CaptureRegion
from src.control.controller import AgentController
from src.control.game_profile import (
    HAND_HAS_FLOWER,
    HAND_INCOMPLETE,
    HAND_MY_TURN,
    HAND_WAITING,
    ITAIWANMJ16,
    check_hand_row,
    classify_hand,
    state_from_visible_hand,
)
from src.control.pipeline import EventIds, run_discard_turn
from src.control.tile_mapper import TileBox
from src.control.window import WindowInfo, WindowLocator
from test_interface.agent_runner import SEAT, make_fake_game_state
from test_interface.fakes import FakeMouse
from test_interface.run_real_game import RepeatClickMouse
from tests._runner import run_module
from tests.helpers import make_hand_mapper

REGION = CaptureRegion(100, 50, 1920, 1200)
HAND17 = list(make_fake_game_state("t").players[SEAT].hand)  # 17 張，沒有花牌


def test_profile_values():
    assert ITAIWANMJ16.title_contains == "愛台灣打麻將 ["
    assert ITAIWANMJ16.hand_size == 16


def test_title_matches_desktop_client_not_web_page():
    desktop = WindowInfo(hwnd=1, title="愛台灣打麻將 [3.4.6.260909.111] x64", left=0, top=0, width=800, height=600)
    web = WindowInfo(hwnd=2, title="愛台灣打麻將 - 個人 - Microsoft​ Edge", left=0, top=0, width=800, height=600)

    assert WindowLocator(ITAIWANMJ16.title_contains, list_fn=lambda: [web, desktop]).find().hwnd == 1
    assert WindowLocator(ITAIWANMJ16.title_contains, list_fn=lambda: [web]).find() is None


def test_classify_hand():
    assert classify_hand(HAND17) == HAND_MY_TURN
    assert classify_hand(HAND17[:16]) == HAND_WAITING
    assert classify_hand(HAND17[:16] + [36]) == HAND_HAS_FLOWER  # 17 張但有花牌
    assert classify_hand(HAND17[:10]) == HAND_INCOMPLETE
    # 已副露 1 組：暗牌 13 張，摸牌後 14 張
    assert classify_hand(HAND17[:14], meld_count=1) == HAND_MY_TURN
    assert classify_hand(HAND17[:13], meld_count=1) == HAND_WAITING


def test_state_from_visible_hand():
    state = state_from_visible_hand("t", HAND17, seat=0, dealer=2, wall_count=57)

    assert state.players[0].hand == HAND17
    assert all(state.players[i].hand == [] for i in (1, 2, 3))  # 其他玩家保持未知
    assert state.dealer == 2 and state.wall_count == 57 and state.current_turn == 0

    with pytest.raises(ValueError):
        state_from_visible_hand("t", HAND17, seat=4)


def test_visible_hand_state_runs_discard_turn():
    state = state_from_visible_hand("t", HAND17)
    mouse = FakeMouse()
    controller = AgentController(game_id="t", mouse=mouse)
    controller.start()
    try:
        result = run_discard_turn(
            state, SEAT, make_hand_mapper(HAND17), REGION, controller,
            game_id="t", ids=EventIds(),
        )
    finally:
        controller.stop()

    assert result.success is True
    assert result.decision.action.id == "discard_0"
    assert mouse.clicks == [(213, 670)]


def _row(indexes, step=158):
    return [TileBox(i, 100 + i * step, 1256, 156, 190) for i in indexes]


def test_hand_row_ok_and_missing_tile():
    assert check_hand_row(_row(range(16))) == []  # 緊貼、等寬、同高

    gap = check_hand_row(_row([0, 1, 3, 4]))  # 缺第 2 張：中間空了一張牌寬
    assert len(gap) == 1 and "漏牌" in gap[0]

    assert check_hand_row([]) == ["沒有偵測到任何手牌"]


def test_hand_row_overlap_and_wrong_height():
    overlap = check_hand_row(_row(range(5), step=50))  # 萬字牌互相誤判、牌框疊在一起
    assert overlap and all("重疊" in p for p in overlap)

    boxes = _row(range(5)) + [TileBox(9, 100 + 5 * 158, 700, 156, 190)]  # 一張跑到別的地方
    wrong_y = check_hand_row(boxes)
    assert any("偏離手牌列" in p for p in wrong_y)


def test_repeat_click_mouse():
    inner, sleeps = FakeMouse(), []
    RepeatClickMouse(inner, times=2, gap=0.25, sleep=sleeps.append).click(5, 6)
    assert inner.clicks == [(5, 6), (5, 6)] and sleeps == [0.25]

    single = FakeMouse()
    RepeatClickMouse(single, times=1, sleep=sleeps.append).click(1, 2)
    assert single.clicks == [(1, 2)]

    with pytest.raises(ValueError):
        RepeatClickMouse(FakeMouse(), times=0)


if __name__ == "__main__":
    run_module(globals(), "test_game_profile")