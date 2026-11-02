import pytest

from src.rules.game_state import GameState, PlayerState


def make_players():
    return {seat: PlayerState(seat_id=seat) for seat in range(4)}


@pytest.mark.parametrize("winner_id", [None, 2])
def test_draw_or_dealer_win_retains_dealer_and_increments_streak(winner_id):
    state = GameState(
        game_id="w5-dealer-retains-test",
        dealer=2,
        lian_zhuang=6,
        players=make_players(),
    )

    state.complete_round(winner_id=winner_id)

    assert state.dealer == 2
    assert state.lian_zhuang == 7
    assert state.is_over


def test_non_dealer_win_rotates_dealer_and_clears_streak():
    state = GameState(
        game_id="w5-dealer-rotates-test",
        dealer=2,
        lian_zhuang=3,
        players=make_players(),
    )

    state.complete_round(winner_id=0)

    assert state.dealer == 3
    assert state.lian_zhuang == 0
    assert state.is_over


def test_invalid_winner_does_not_change_dealer_or_streak():
    state = GameState(
        game_id="w5-invalid-winner-test",
        dealer=2,
        lian_zhuang=3,
        players=make_players(),
    )

    with pytest.raises(ValueError, match="Unknown winner seat"):
        state.complete_round(winner_id=4)

    assert state.dealer == 2
    assert state.lian_zhuang == 3
    assert not state.is_over


def test_duplicate_winner_seats_are_rejected_without_changing_round_state():
    state = GameState(
        game_id="w5-duplicate-winner-test",
        dealer=2,
        lian_zhuang=3,
        players=make_players(),
    )

    with pytest.raises(ValueError, match="Winner seats must be unique"):
        state.complete_round(winner_seats=[1, 1], is_draw=False)

    assert state.dealer == 2
    assert state.lian_zhuang == 3
    assert not state.is_over


@pytest.mark.parametrize(
    "winner_seats, expected_dealer, expected_streak",
    [
        ([0, 2], 2, 8),
        ([0, 1], 3, 0),
    ],
)
def test_multiple_unique_winners_advance_dealer_once(
    winner_seats, expected_dealer, expected_streak
):
    state = GameState(
        game_id="w5-multiple-winners-dealer-test",
        dealer=2,
        lian_zhuang=7,
        players=make_players(),
    )

    state.complete_round(winner_seats=winner_seats, is_draw=False)

    assert state.dealer == expected_dealer
    assert state.lian_zhuang == expected_streak
    assert state.is_over


def test_completed_round_cannot_increment_streak_twice():
    state = GameState(
        game_id="w5-complete-round-once-test",
        players=make_players(),
    )
    state.complete_round()

    with pytest.raises(ValueError, match="already been completed"):
        state.complete_round()

    assert state.lian_zhuang == 1


def test_dealer_rotation_wraps_from_seat_three_to_zero():
    state = GameState(
        game_id="w5-dealer-wraparound-test",
        dealer=3,
        lian_zhuang=4,
        players=make_players(),
    )

    state.complete_round(winner_id=0)

    assert state.dealer == 0
    assert state.lian_zhuang == 0
    assert state.is_over
