import pytest

from src.common.schemas import ActionType
from src.rules.fan_calculator import FanCalculator
from src.rules.game_state import Meld
from src.rules.settlement_calculator import SettlementCalculator


def test_menqing_self_draw_calculates_fans_and_settles_scores():
    hand = [
        0, 1, 2,
        3, 4, 5,
        9, 10, 11,
        18, 19, 20,
        21, 22, 23,
        24, 24,
    ]
    fans, details = FanCalculator().calculate(
        hand,
        winner_seat=1,
        dealer_seat=0,
        is_self_draw=True,
    )

    assert fans == 4
    assert details == [("底台", 1), ("自摸", 1), ("門清", 1), ("平胡", 1)]

    scores = SettlementCalculator().settle(
        {0: 20000, 1: 20000, 2: 20000, 3: 20000},
        winner_seat=1,
        total_fans=fans,
        is_self_draw=True,
    )

    assert scores == {0: 19600, 1: 21200, 2: 19600, 3: 19600}
    assert sum(scores.values()) == 80000


def test_dealer_tai_and_consecutive_dealer_tai_are_added_for_dealer_win():
    fans, details = FanCalculator().calculate(
        [0, 1, 2, 3, 4, 5, 9, 10, 11, 18, 19, 20, 21, 22, 23, 24, 24],
        winner_seat=2,
        dealer_seat=2,
        lian_zhuang=3,
    )

    assert fans == 7
    assert details == [
        ("底台", 1),
        ("莊家台", 1),
        ("連莊台", 3),
        ("門清", 1),
        ("平胡", 1),
    ]


def test_discard_win_is_paid_only_by_loser():
    scores = SettlementCalculator().settle(
        {0: 20000, 1: 20000, 2: 20000, 3: 20000},
        winner_seat=0,
        total_fans=3,
        is_self_draw=False,
        loser_seat=2,
    )

    assert scores == {0: 20300, 1: 20000, 2: 19700, 3: 20000}


def test_ping_hu_requires_no_flowers_honors_or_triplets():
    fans, details = FanCalculator().calculate(
        [0, 1, 2, 3, 4, 5, 9, 10, 11, 18, 19, 20, 21, 22, 23, 27, 27],
        winner_seat=1,
        dealer_seat=0,
        flowers=[34],
    )

    assert fans == 2
    assert details == [("底台", 1), ("門清", 1)]


def test_open_meld_disables_menqing_but_keeps_sequence_hand_shape():
    meld = Meld(
        meld_type=ActionType.CHI,
        tiles=[0, 1, 2],
        from_player=0,
    )
    hand = [3, 4, 5, 9, 10, 11, 18, 19, 20, 21, 22, 23, 24, 24]

    fans, details = FanCalculator().calculate(
        hand,
        winner_seat=1,
        dealer_seat=0,
        melds=[meld],
    )

    assert fans == 2
    assert details == [("底台", 1), ("平胡", 1)]


@pytest.mark.parametrize(
    "scores, kwargs, message",
    [
        ({0: 1, 1: 1, 2: 1}, {"winner_seat": 0}, "Scores must be provided"),
        (
            {0: 1, 1: 1, 2: 1, 3: 1},
            {"winner_seat": 0, "total_fans": 1, "is_self_draw": False},
            "valid loser seat is required",
        ),
    ],
)
def test_settlement_rejects_invalid_inputs(scores, kwargs, message):
    with pytest.raises(ValueError, match=message):
        SettlementCalculator().settle(scores, **kwargs)
