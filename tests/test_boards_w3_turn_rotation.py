import pytest

from src.common.schemas import ActionType
from src.rules.game_state import GameState, PlayerState
from src.rules.rule import Action


def make_players():
    return {seat: PlayerState(seat_id=seat) for seat in range(4)}


def test_discards_rotate_turn_and_update_each_player_river():
    players = {
        seat: PlayerState(seat_id=seat, hand=[seat])
        for seat in range(4)
    }
    state = GameState(game_id="discard-turn-test", players=players)

    for seat in range(4):
        state.apply_action(
            seat,
            Action(action_type=ActionType.DISCARD, tile_id=seat),
        )
        assert state.current_turn == (seat + 1) % 4
        assert state.players[seat].hand == []
        assert state.players[seat].discards == [seat]
        assert state.last_discard.player_id == seat
        assert state.last_discard.tile_id == seat


def test_out_of_turn_discard_leaves_state_unchanged():
    state = GameState(game_id="out-of-turn-discard-test", players=make_players())
    state.players[1].hand = [5]

    with pytest.raises(ValueError, match="It is player 0's turn"):
        state.apply_action(1, Action(action_type=ActionType.DISCARD, tile_id=5))

    assert state.players[1].hand == [5]
    assert state.players[1].discards == []
    assert state.current_turn == 0
    assert state.last_discard is None


def test_discard_rejects_missing_and_flower_tiles_without_mutation():
    state = GameState(game_id="invalid-discard-test", players=make_players())
    state.players[0].hand = [34]

    with pytest.raises(ValueError, match="between 0 and 33"):
        state.apply_action(0, Action(action_type=ActionType.DISCARD, tile_id=34))
    with pytest.raises(ValueError, match="does not have tile 8"):
        state.apply_action(0, Action(action_type=ActionType.DISCARD, tile_id=8))

    assert state.players[0].hand == [34]
    assert state.players[0].discards == []
    assert state.current_turn == 0
