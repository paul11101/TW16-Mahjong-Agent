from collections import Counter
from random import Random

import pytest

from src.rules.game_state import GameState, PlayerState, create_shuffled_wall


def make_players():
    return {seat: PlayerState(seat_id=seat) for seat in range(4)}


def test_deal_assigns_hand_sizes_and_preserves_all_tiles():
    wall = create_shuffled_wall(Random(42))
    original_counts = Counter(wall)
    state = GameState(
        game_id="deal-test",
        dealer=2,
        players=make_players(),
        wall=wall,
    )

    state.deal()

    assert [len(state.players[seat].hand) for seat in range(4)] == [16, 16, 17, 16]
    assert all(
        0 <= tile_id < 34
        for player in state.players.values()
        for tile_id in player.hand
    )
    assert all(
        34 <= tile_id <= 41
        for player in state.players.values()
        for tile_id in player.flowers
    )
    assert state.wall_count == len(state.wall) >= 16
    assert state.current_turn == state.dealer == 2
    assert (
        Counter(
            tile_id
            for player in state.players.values()
            for tile_id in player.hand + player.flowers
        )
        + Counter(state.wall)
        == original_counts
    )


def test_failed_deal_does_not_mutate_state():
    wall = list(range(17))
    state = GameState(
        game_id="incomplete-deal-test",
        players=make_players(),
        wall=wall,
    )

    with pytest.raises(ValueError, match="Not enough drawable tiles"):
        state.deal()

    assert state.wall == wall
    assert state.wall_count == 144
    assert all(not player.hand and not player.flowers for player in state.players.values())
    assert state.current_turn == state.dealer == 0
