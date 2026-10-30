"""反應只從「畫面上可點的按鈕」中選：過水後「胡」按鈕停用時，Agent 不再選胡。

執行方式（專案根目錄）：
    python -m tests.test_visible_buttons
或
    python -m pytest tests/test_visible_buttons.py -v
"""

from src.common.schemas import ActionType
from src.control.button_mapper import ButtonBox, ButtonMapper, filter_to_visible_buttons
from src.control.capture import CaptureRegion
from src.control.controller import AgentController
from src.control.pipeline import EventIds, run_reaction_turn
from src.rules.game_state import GameState, LastDiscard, PlayerState
from src.strategy.interfaces import LegalAction
from test_interface.fakes import FakeMouse
from tests._runner import run_module

SEAT = 0
# 上家（玩家 3）打出 3 之後，這手牌規則會提供 胡／吃／碰／過
WIN_HAND = [0, 1, 2, 3, 3, 4, 5, 6, 9, 10, 11, 18, 19, 20, 27, 27]
PASS_HAND = [0, 1, 2, 3, 3, 4, 5, 6, 9, 10, 11, 18, 19, 20, 27, 30]
REGION = CaptureRegion(0, 0, 800, 600)


def _state(hand, target):
    return GameState(
        game_id="t", current_turn=SEAT, wall_count=80,
        last_discard=LastDiscard(player_id=3, tile_id=target),
        players={i: PlayerState(seat_id=i, hand=list(hand) if i == SEAT else []) for i in range(4)},
    )


def _mapper(win_enabled):
    mapper = ButtonMapper(frame_size=(800, 600))
    mapper.update(buttons=[
        ButtonBox("win", 100, 100, 40, 20, enabled=win_enabled),
        ButtonBox("pass", 200, 100, 40, 20),
    ])
    return mapper


def _run(state, mapper, **kw):
    mouse = FakeMouse()
    controller = AgentController(game_id="t", mouse=mouse)
    controller.start()
    try:
        result = run_reaction_turn(
            state, SEAT, mapper, REGION, controller, game_id="t", ids=EventIds(), **kw
        )
    finally:
        controller.stop()
    return result, mouse.clicks


def _legal():
    return [
        LegalAction(id="win_3", action=ActionType.WIN, tile=3),
        LegalAction(id="chi_1_2_3", action=ActionType.CHI, tile=3, tiles=(1, 2, 3)),
        LegalAction(id="pong_3", action=ActionType.PONG, tile=3, tiles=(3, 3, 3)),
        LegalAction(id="pass", action=ActionType.PASS),
    ]


def test_filter_keeps_only_enabled_buttons_and_pass():
    mapper = ButtonMapper(frame_size=(800, 600))
    mapper.update(buttons=[
        ButtonBox("chi", 0, 0, 10, 10),
        ButtonBox("pong", 20, 0, 10, 10, enabled=False),
        ButtonBox("pass", 40, 0, 10, 10),
    ])
    kept, dropped = filter_to_visible_buttons(_legal(), mapper)

    assert [a.id for a in kept] == ["chi_1_2_3", "pass"]
    assert [a.id for a in dropped] == ["win_3", "pong_3"]


def test_filter_does_nothing_without_button_layout():
    kept, dropped = filter_to_visible_buttons(_legal(), ButtonMapper(frame_size=(800, 600)))

    assert len(kept) == 4 and dropped == []


def test_disabled_win_button_without_filter_is_stuck():
    result, clicks = _run(_state(WIN_HAND, 3), _mapper(win_enabled=False))

    assert result.decision.action.action == ActionType.WIN
    assert result.error == "BUTTON_DISABLED" and clicks == []  # 舊行為：選了胡卻點不到


def test_disabled_win_button_with_filter_passes():
    result, clicks = _run(_state(WIN_HAND, 3), _mapper(win_enabled=False), only_visible_buttons=True)

    assert result.success is True
    assert result.decision.action.action == ActionType.PASS
    assert clicks == [(220, 110)]  # 點「過」


def test_enabled_win_button_is_still_chosen_with_filter():
    result, clicks = _run(_state(WIN_HAND, 3), _mapper(win_enabled=True), only_visible_buttons=True)

    assert result.decision.action.action == ActionType.WIN
    assert clicks == [(120, 110)]


def test_only_pass_is_still_skipped_with_filter():
    result, clicks = _run(_state(PASS_HAND, 33), _mapper(win_enabled=False), only_visible_buttons=True)

    assert result.skipped is True and clicks == []


if __name__ == "__main__":
    run_module(globals(), "test_visible_buttons")