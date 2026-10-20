from collections import Counter
from random import Random

from src.rules.game_state import GameState, PlayerState, create_shuffled_wall


def test_shuffled_wall_has_full_tile_counts_and_is_seedable():
    wall = create_shuffled_wall(Random(42))
    counts = Counter(wall)

    assert len(wall) == 144
    assert set(counts) == set(range(42))
    assert all(counts[tile_id] == 4 for tile_id in range(34))
    assert all(counts[tile_id] == 1 for tile_id in range(34, 42))
    assert wall == create_shuffled_wall(Random(42))
    assert wall != sorted(wall)


def test_game_state_initializes_full_wall():
    players = {seat: PlayerState(seat_id=seat) for seat in range(4)}
    state = GameState(game_id="shuffle-test", players=players)

    assert len(state.wall) == state.wall_count == 144
