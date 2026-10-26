from random import Random

import pytest

from src.rules.game_state import GameState, PlayerState
from src.rules.state_machine import GameStage, MahjongStateMachine


def make_state(dealer=0, round_wind=0, lian_zhuang=0):
    return GameState(
        game_id="dealer-state-machine-test",
        dealer=dealer,
        round_wind=round_wind,
        lian_zhuang=lian_zhuang,
        players={seat: PlayerState(seat_id=seat) for seat in range(4)},
    )


def test_dealer_self_draw_retains_dealer_and_increments_streak():
    state = make_state(dealer=1, lian_zhuang=2)

    state.complete_round(winner_seats=[1], is_draw=False)

    assert state.dealer == 1
    assert state.lian_zhuang == 3


def test_dealer_retains_when_dealer_is_among_multiple_winners():
    state = make_state(dealer=1, lian_zhuang=2)

    state.complete_round(winner_seats=[2, 1], is_draw=False)

    assert state.dealer == 1
    assert state.lian_zhuang == 3


def test_non_dealer_win_rotates_dealer_and_resets_streak():
    state = make_state(dealer=1, lian_zhuang=3)

    state.complete_round(winner_seats=[3], is_draw=False)

    assert state.dealer == 2
    assert state.lian_zhuang == 0


def test_north_dealer_rotation_advances_east_wind_to_south_wind():
    state = make_state(dealer=3, round_wind=0, lian_zhuang=2)

    state.complete_round(winner_seats=[0], is_draw=False)

    assert state.dealer == 0
    assert state.lian_zhuang == 0
    assert state.round_wind == 1


@pytest.mark.parametrize(
    ("winner_seats", "is_draw", "expected_dealer", "expected_streak"),
    [
        ([0], False, 0, 1),
        ([], True, 0, 1),
    ],
)
def test_round_end_reinitializes_and_returns_to_player_turn(
    winner_seats,
    is_draw,
    expected_dealer,
    expected_streak,
):
    state = make_state(lian_zhuang=0)
    machine = MahjongStateMachine(state, rng=Random(42))
    machine.start_round()
    machine.begin_settlement()

    machine.process_round_end(winner_seats=winner_seats, is_draw=is_draw)

    assert machine.stage == GameStage.PLAYER_TURN
    assert state.is_over is False
    assert state.dealer == expected_dealer
    assert state.lian_zhuang == expected_streak
    assert state.current_turn == state.dealer
    assert all(
        len(state.players[seat].hand) == (17 if seat == state.dealer else 16)
        for seat in range(4)
    )


def test_round_end_requires_settlement_stage():
    machine = MahjongStateMachine(make_state(), rng=Random(1))

    with pytest.raises(ValueError, match="only be processed from settlement"):
        machine.process_round_end(is_draw=True)


def test_north_dealer_state_machine_rotates_wind_before_next_deal():
    state = make_state(dealer=3, round_wind=0)
    machine = MahjongStateMachine(state, rng=Random(13))
    machine.start_round()
    machine.begin_settlement()

    machine.process_round_end(winner_seats=[1], is_draw=False)

    assert state.dealer == 0
    assert state.round_wind == 1
    assert machine.stage == GameStage.PLAYER_TURN
