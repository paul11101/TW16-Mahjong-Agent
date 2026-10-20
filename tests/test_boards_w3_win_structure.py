import pytest

from src.common.schemas import ActionType
from src.rules.game_state import GameState, PlayerState, is_basic_win


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
    players = {
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
    }
    state = GameState(game_id="open-hand-win-test", players=players)

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
