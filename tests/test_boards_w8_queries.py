"""W8：GameState 查詢介面（反應動作含過水、行動階段、結果、牌數守恆）。

執行方式（專案根目錄）：
    python -m tests.test_boards_w8_queries
或
    python -m pytest tests/test_boards_w8_queries.py -v
"""

from random import Random

import pytest

from src.common.schemas import ActionType
from src.rules.game_state import GameState, LastDiscard, PlayerState
from src.rules.rule import Action
from tests._runner import run_module

READY = [0, 1, 2, 3, 4, 5, 9, 10, 11, 18, 19, 20, 27, 27, 27, 31]  # 等 31 可胡


def make_players():
    return {seat: PlayerState(seat_id=seat) for seat in range(4)}


def kinds(actions):
    return {ActionType(action.action_type) for action in actions}


def test_reaction_actions_include_win_then_block_after_pass():
    players = make_players()
    players[0].discards = [31]
    players[1].hand = list(READY)
    state = GameState(
        game_id="w8-react",
        current_turn=1,
        players=players,
        last_discard=LastDiscard(player_id=0, tile_id=31),
    )

    assert kinds(state.get_reaction_actions(1)) == {ActionType.WIN, ActionType.PASS}

    state.apply_action(1, Action(action_type=ActionType.PASS))  # 有胡卻過 -> 過水
    assert state.players[1].passed_win
    assert kinds(state.get_reaction_actions(1)) == {ActionType.PASS}


def test_reaction_actions_reject_missing_or_own_discard():
    state = GameState(game_id="w8-none", players=make_players())
    with pytest.raises(ValueError, match="no opponent discard"):
        state.get_reaction_actions(1)

    state.last_discard = LastDiscard(player_id=1, tile_id=5)
    with pytest.raises(ValueError, match="no opponent discard"):
        state.get_reaction_actions(1)
    with pytest.raises(ValueError, match="Unknown player seat"):
        state.get_reaction_actions(9)


def test_action_phase_and_seats_to_act():
    players = make_players()
    players[0].hand = [27]
    players[2].hand = [27, 27, 3]
    state = GameState(game_id="w8-phase", current_turn=0, players=players, wall=[])

    assert state.action_phase(0) == "my_turn" and state.seats_to_act() == [0]

    state.apply_action(0, Action(action_type=ActionType.DISCARD, tile_id=27))
    assert state.action_phase(0) == "waiting"
    assert state.action_phase(1) == "waiting"  # 輪到他，但只能 PASS
    assert state.action_phase(2) == "reaction"  # 可以碰
    assert state.seats_to_act() == [2]

    state.complete_round()
    assert all(state.action_phase(seat) == "over" for seat in range(4))
    assert state.seats_to_act() == []


def test_result_and_winner_seats_follow_round_lifecycle():
    state = GameState(game_id="w8-result", players=make_players())
    assert state.result is None and state.winner_seats == []

    state.complete_round(winner_id=1)
    assert state.result == "win" and state.winner_seats == [1]

    state.next_round(rng=Random(1))
    assert state.result is None and state.winner_seats == []

    state.complete_round()
    assert state.result == "draw" and state.winner_seats == []

    state.reset_round_state()
    assert state.winner_seats == [] and state.result is None


def test_check_card_conservation():
    state = GameState(game_id="w8-conserve", players=make_players())
    state.init_next_round(rng=Random(5))
    assert state.check_card_conservation()

    state.players[1].hand.pop()  # 少一張
    assert not state.check_card_conservation()


if __name__ == "__main__":
    run_module(globals(), "test_boards_w8_queries")
