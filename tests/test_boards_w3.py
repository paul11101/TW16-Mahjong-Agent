from collections import Counter
from random import Random

import pytest

from src.common.schemas import ActionType
from src.rules.game_state import (
    GameState,
    PlayerState,
    create_shuffled_wall,
    is_basic_win,
)
from src.rules.rule import Action


def make_players():
    return {seat: PlayerState(seat_id=seat) for seat in range(4)}


def test_basic_win_accepts_five_melds_and_a_pair():
    hand = [
        0, 1, 2,
        9, 10, 11,
        18, 19, 20,
        27, 27, 27,
        31, 31, 31,
        33, 33,
    ]

    assert is_basic_win(hand)


def test_basic_win_rejects_incomplete_and_cross_suit_structures():
    incomplete_hand = [
        0, 1, 2,
        9, 10, 11,
        18, 19, 20,
        27, 27, 27,
        31, 31, 31,
        32, 33,
    ]
    cross_suit_sequence = [
        8, 9, 10,
        9, 10, 11,
        18, 19, 20,
        27, 27, 27,
        31, 31, 31,
        33, 33,
    ]

    assert not is_basic_win(incomplete_hand)
    assert not is_basic_win([0, 1, 2])
    assert not is_basic_win(cross_suit_sequence)


def test_basic_win_accounts_for_exposed_melds():
    hand = [
        0, 1, 2,
        9, 10, 11,
        18, 19, 20,
        27, 27, 27,
        33, 33,
    ]
    state = GameState(
        game_id="open-hand-win-test",
        players={
            0: PlayerState(
                seat_id=0,
                hand=hand,
                melds=[{
                    "meld_type": ActionType.PONG,
                    "tiles": [30, 30, 30],
                    "from_player": 1,
                }],
            ),
            **{seat: PlayerState(seat_id=seat) for seat in range(1, 4)},
        },
    )

    assert is_basic_win(hand, meld_count=1)
    assert state.is_basic_win(0)
    assert not is_basic_win(hand)


@pytest.mark.parametrize("hand", [[0] * 5, [34] * 17])
def test_basic_win_rejects_invalid_tile_counts(hand):
    with pytest.raises(ValueError):
        is_basic_win(hand)


def test_basic_win_rejects_invalid_meld_count():
    with pytest.raises(ValueError, match="Meld count"):
        is_basic_win([], meld_count=6)


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
    state = GameState(game_id="shuffle-test", players=make_players())

    assert len(state.wall) == state.wall_count == 144


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


def test_discards_rotate_turn_and_update_each_player_river():
    state = GameState(
        game_id="discard-turn-test",
        players={
            seat: PlayerState(seat_id=seat, hand=[seat])
            for seat in range(4)
        },
    )

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

