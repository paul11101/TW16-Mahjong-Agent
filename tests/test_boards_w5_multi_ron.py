from src.common.schemas import ActionType
from src.rules.game_state import GameState, LastDiscard, PlayerState
from src.rules.rule import Action


def make_reaction_state(target_tile=2):
    players = {seat: PlayerState(seat_id=seat) for seat in range(4)}
    players[0].discards = [target_tile]
    return GameState(
        game_id="w5-multi-ron-test",
        players=players,
        last_discard=LastDiscard(player_id=0, tile_id=target_tile),
    )


def test_multiple_ron_candidates_only_return_nearest_winner():
    state = make_reaction_state()
    reactions = {
        1: Action(action_type=ActionType.WIN, tile_id=2),
        2: Action(action_type=ActionType.WIN, tile_id=2),
        3: Action(action_type=ActionType.PONG, tile_id=2),
    }

    assert state.resolve_reaction_priority(reactions) == {1: reactions[1]}


def test_nearest_ron_winner_order_wraps_around_seat_zero():
    state = make_reaction_state()
    state.last_discard.player_id = 3
    reactions = {
        0: Action(action_type=ActionType.WIN, tile_id=2),
        2: Action(action_type=ActionType.WIN, tile_id=2),
    }

    assert state.resolve_reaction_priority(reactions) == {0: reactions[0]}
