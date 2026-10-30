"""自己回合的自摸胡與槓：規則動作、整合端點擊、測試牌桌、階段判斷。

執行方式（專案根目錄）：
    python -m tests.test_turn_actions
或
    python -m pytest tests/test_turn_actions.py -v
"""

from src.common.schemas import ActionType
from src.control.batch import aggregate
from src.control.button_mapper import ButtonBox, ButtonMapper, ChoiceBox
from src.control.capture import CaptureRegion
from src.control.controller import AgentController
from src.control.game_profile import state_from_visible_hand
from src.control.game_runner import PHASE_MY_TURN
from src.control.pipeline import (
    EventIds,
    filter_turn_actions,
    get_turn_rules_actions,
    run_discard_turn,
)
from src.rules.game_state import Meld
from src.strategy.action_policy import ActionPolicy
from src.strategy.adapters import actions_to_legal_actions
from test_interface.agent_runner import SEAT
from test_interface.fakes import FakeMouse
from test_interface.scripted_policy import ScriptedPolicy
from test_interface.sim_table import PHASE_OVER, PHASE_TURN, SimTable
from test_interface.web_observer import classify_view
from tests._runner import run_module
from tests.helpers import make_hand_mapper

REGION = CaptureRegion(100, 50, 1920, 1200)
NAMES = ["chi", "pong", "kong", "win", "pass"]

WIN_HAND = [0, 1, 2, 9, 10, 11, 18, 19, 20, 27, 27, 27, 31, 31, 31, 33, 33]  # 5 組面子 + 對子
KONG_HAND = [4, 4, 4, 4, 0, 1, 2, 9, 10, 11, 18, 19, 20, 27, 27, 31, 33]  # 一組暗槓
TWO_KONG_HAND = [4, 4, 4, 4, 10, 10, 10, 10, 0, 1, 2, 18, 19, 20, 27, 31, 33]  # 兩組暗槓
JIA_HAND = [4, 0, 1, 2, 9, 10, 11, 18, 19, 20, 27, 27, 31, 33]  # 已碰 4，手上還有第四張
PONG4 = Meld(meld_type=ActionType.PONG, tiles=[4, 4, 4], from_player=1)


def _buttons(enabled, choices=()):
    """chi 中心 (120,110)、pong (170,110)、kong (220,110)、win (270,110)、pass (320,110)。"""
    mapper = ButtonMapper(frame_size=(1920, 1200))
    mapper.update(
        buttons=[ButtonBox(n, 100 + i * 50, 100, 40, 20, enabled=n in enabled) for i, n in enumerate(NAMES)],
        choices=choices,
    )
    return mapper


def _state(hand, melds=()):
    state = state_from_visible_hand("t", hand)
    state.players[SEAT].melds = list(melds)
    return state


def _kinds(actions):
    return {ActionType(a.action_type) for a in actions}


def _run(hand, *, policy, button_mapper, melds=()):
    mouse = FakeMouse()
    controller = AgentController(game_id="t", mouse=mouse)
    controller.start()
    try:
        result = run_discard_turn(
            _state(hand, melds), SEAT, make_hand_mapper(hand), REGION, controller,
            game_id="t", ids=EventIds(), policy=policy, button_mapper=button_mapper,
        )
    finally:
        controller.stop()
    return result, mouse.clicks


# ------------------------------------------------------------------ 規則動作與過濾

def test_rules_actions_include_self_draw_win():
    kinds = _kinds(get_turn_rules_actions(_state(WIN_HAND), SEAT))
    assert ActionType.WIN in kinds and ActionType.DISCARD in kinds


def test_rules_actions_include_an_and_jia_kong():
    an = get_turn_rules_actions(_state(KONG_HAND), SEAT)
    assert {(a.tile_id, a.kong_type) for a in an if ActionType(a.action_type) == ActionType.KONG} == {(4, "an")}

    jia = get_turn_rules_actions(_state(JIA_HAND, [PONG4]), SEAT)
    assert {(a.tile_id, a.kong_type) for a in jia if ActionType(a.action_type) == ActionType.KONG} == {(4, "jia")}


def test_filter_turn_actions():
    legal = actions_to_legal_actions(get_turn_rules_actions(_state(WIN_HAND), SEAT))

    def kinds(mapper):
        return {ActionType(a.action) for a in filter_turn_actions(legal, mapper)}

    assert kinds(None) == {ActionType.DISCARD}
    assert kinds(_buttons(())) == {ActionType.DISCARD}  # 按鈕都沒亮
    assert kinds(_buttons(("win",))) == {ActionType.DISCARD, ActionType.WIN}
    assert kinds(ButtonMapper(frame_size=(1920, 1200))) == {ActionType.DISCARD}  # 沒有按鈕資料


# ------------------------------------------------------------------ 整合端點擊

def test_self_draw_win_clicks_win_button():
    result, clicks = _run(WIN_HAND, policy=ActionPolicy(), button_mapper=_buttons(("win",)))

    assert result.success is True
    assert result.decision.action.action == ActionType.WIN
    assert clicks == [(370, 160)]  # win 按鈕中心 (270,110) + 視窗偏移 (100,50)


def test_win_is_not_offered_without_buttons():
    result, clicks = _run(WIN_HAND, policy=ActionPolicy(), button_mapper=None)

    assert result.decision.action.action == ActionType.DISCARD
    assert result.legal_count == 12  # 12 種牌各一個出牌動作
    assert len(clicks) == 1


def test_single_kong_is_one_click():
    result, clicks = _run(KONG_HAND, policy=ScriptedPolicy("kong_4"), button_mapper=_buttons(("kong",)))

    assert result.success is True and result.decision.action.kong_type == "an"
    assert clicks == [(320, 160)]


def test_two_kongs_need_button_then_choice():
    choices = [ChoiceBox("kong_4", 200, 200, 80, 20), ChoiceBox("kong_10", 300, 200, 80, 20)]
    result, clicks = _run(
        TWO_KONG_HAND, policy=ScriptedPolicy("kong_10"), button_mapper=_buttons(("kong",), choices)
    )

    assert result.success is True and result.plan.needs_choice is True
    assert clicks == [(320, 160), (440, 260)]  # 先點「槓」，再點 kong_10 的組合


def test_disabled_kong_button_falls_back_to_discard():
    result, clicks = _run(KONG_HAND, policy=ActionPolicy(), button_mapper=_buttons(("win",)))

    assert result.decision.action.action == ActionType.DISCARD
    assert result.legal_count == 13 and len(clicks) == 1


# ------------------------------------------------------------------ 測試牌桌

def test_sim_table_self_draw_win():
    table = SimTable(1)
    table.state.players[0].hand = list(WIN_HAND)
    view = table.view()

    assert view["buttons"]["win"] is True and view["buttons"]["pass"] is False
    assert classify_view(view) == PHASE_MY_TURN  # 有按鈕亮，仍然是自己回合
    assert table.agent_react("button", "win") is True
    assert table.phase == PHASE_OVER and table.winner == 0 and table.result == "win"


def test_sim_table_concealed_kong():
    table = SimTable(1)
    table.state.players[0].hand = list(KONG_HAND)
    view = table.view()
    version = view["version"]

    assert view["buttons"]["kong"] is True and view["buttons"]["win"] is False
    assert table.agent_react("button", "kong") is True

    me = table.state.players[0]
    assert len(me.melds) == 1 and me.melds[0].kong_type == "an"
    assert len(me.hand) == 14  # 13 張 + 補牌 1 張，還是自己回合
    assert table.phase == PHASE_TURN and table.view()["version"] > version


def test_sim_table_two_kongs_two_steps():
    table = SimTable(1)
    table.state.players[0].hand = list(TWO_KONG_HAND)

    assert table.agent_react("choice", choice_id="kong_99") is False
    assert table.agent_react("button", "kong") is True  # 第一步：只是選了「槓」
    assert len(table.state.players[0].melds) == 0
    assert table.agent_react("choice", choice_id="kong_10") is True
    assert table.state.players[0].melds[0].tiles == [10, 10, 10, 10]


def test_sim_table_added_kong():
    table = SimTable(1)
    me = table.state.players[0]
    me.hand, me.melds = list(JIA_HAND), [PONG4]

    assert table.view()["buttons"]["kong"] is True
    assert table.agent_react("button", "kong") is True
    assert len(me.melds) == 1 and me.melds[0].kong_type == "jia" and len(me.melds[0].tiles) == 4
    assert len(me.hand) == 14


def test_sim_table_rejects_buttons_that_are_not_lit():
    table = SimTable(1)
    table.state.players[0].hand = list(KONG_HAND)

    assert table.agent_react("button", "win") is False  # 不能胡
    assert table.agent_react("button", "pass") is False  # 自己回合沒有「過」
    assert table.agent_react("button", "chi") is False


# ------------------------------------------------------------------ 報表

def test_batch_counts_agent_wins_and_draws():
    rows = [
        {"game_id": "a", "finished": True, "winner": 0, "result": "win"},
        {"game_id": "b", "finished": True, "winner": 2, "result": "win"},
        {"game_id": "c", "finished": True, "winner": None, "result": "draw"},
    ]
    report = aggregate("w", rows)

    assert report.agent_wins == 1 and report.draw_games == 1


if __name__ == "__main__":
    run_module(globals(), "test_turn_actions")