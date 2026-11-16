from collections import Counter

import pytest

from src.common.schemas import ActionType
from src.rules.game_state import GameState, LastDiscard, PlayerState


def make_players():
    return {seat: PlayerState(seat_id=seat) for seat in range(4)}


def test_result_tracks_winners_and_is_cleared_between_rounds():
    state = GameState(game_id="result-test", players=make_players())
    assert state.result is None

    winners = [1, 3]
    state.complete_round(winner_seats=winners, is_draw=False)
    winners.clear()

    assert state.result == "win"
    assert state.winner_seats == [1, 3]

    state.reset_round_state()

    assert state.result is None
    assert state.winner_seats == []


def test_result_reports_draw_and_next_round_clears_winners():
    state = GameState(game_id="draw-result-test", players=make_players())
    state.complete_round()

    assert state.result == "draw"
    assert state.winner_seats == []

    state.next_round()

    assert state.result is None
    assert state.winner_seats == []


def test_get_reaction_actions_includes_win_and_respects_passed_win():
    state = GameState(game_id="reaction-test", players=make_players())
    state.players[1].hand = [
        1, 2, 3, 4, 5, 9, 10, 11, 18, 19, 20, 27, 27, 27, 28, 28
    ]
    state.last_discard = LastDiscard(player_id=0, tile_id=0)

    actions = state.get_reaction_actions(1)

    assert ActionType.WIN in [ActionType(action.action_type) for action in actions]
    assert ActionType.CHI in [ActionType(action.action_type) for action in actions]

    state.players[1].passed_win = True
    passed_actions = state.get_reaction_actions(1)

    assert ActionType.WIN not in [
        ActionType(action.action_type) for action in passed_actions
    ]


def test_action_phase_and_seats_to_act_only_include_decisions():
    state = GameState(game_id="phase-test", players=make_players(), current_turn=2)
    state.players[1].hand = [5, 5]
    state.last_discard = LastDiscard(player_id=0, tile_id=5)

    assert state.action_phase(0) == "waiting"
    assert state.action_phase(1) == "reaction"
    assert state.action_phase(2) == "waiting"
    assert state.seats_to_act() == [1]

    state.last_discard = None

    assert state.seats_to_act() == [2]
    state.complete_round()
    assert state.action_phase(2) == "over"


@pytest.mark.parametrize("seat", [4, -1])
def test_action_phase_rejects_unknown_seats(seat):
    state = GameState(game_id="invalid-phase-seat-test", players=make_players())

    with pytest.raises(ValueError, match="Unknown player seat"):
        state.action_phase(seat)


def test_check_card_conservation_checks_tile_counts_and_wall_count():
    full_tiles = [tile for tile in range(34) for _ in range(4)] + list(range(34, 42))
    state = GameState(
        game_id="conservation-query-test",
        wall=full_tiles,
        wall_count=len(full_tiles),
        players=make_players(),
    )

    assert state.check_card_conservation()

    state.wall.pop()
    state.players[0].hand.append(34)
    assert not state.check_card_conservation()

    state.wall_count = len(state.wall)
    assert not state.check_card_conservation()
