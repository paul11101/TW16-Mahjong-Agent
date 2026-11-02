import pytest

from src.common.schemas import ActionType
from src.rules.fan_calculator import FanCalculator
from src.rules.game_state import Meld, is_basic_win
from src.rules.rule import RulesetConfig
from src.rules.settlement_calculator import SettlementCalculator


ALL_SEQUENCE_HAND = [
    0, 1, 2,
    3, 4, 5,
    9, 10, 11,
    18, 19, 20,
    21, 22, 23,
    24, 24,
]


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


@pytest.mark.parametrize(
    "winner_seat, dealer_seat, lian_zhuang, is_self_draw, config, expected_fans, expected_details",
    [
        (1, 0, 0, False, None, 3, [("底台", 1), ("門清", 1), ("平胡", 1)]),
        (1, 0, 0, True, None, 4, [("底台", 1), ("自摸", 1), ("門清", 1), ("平胡", 1)]),
        (0, 0, 0, False, None, 4, [("底台", 1), ("莊家台", 1), ("門清", 1), ("平胡", 1)]),
        (0, 0, 0, True, None, 5, [("底台", 1), ("自摸", 1), ("莊家台", 1), ("門清", 1), ("平胡", 1)]),
        (2, 2, 2, False, None, 6, [("底台", 1), ("莊家台", 1), ("連莊台", 2), ("門清", 1), ("平胡", 1)]),
        (3, 3, 5, False, None, 9, [("底台", 1), ("莊家台", 1), ("連莊台", 5), ("門清", 1), ("平胡", 1)]),
        (1, 0, 99, False, None, 3, [("底台", 1), ("門清", 1), ("平胡", 1)]),
        (
            1,
            0,
            0,
            True,
            RulesetConfig(scoring_tai={
                "base_tai": 0,
                "self_draw": 0,
                "in_hand": 0,
                "ping_hu": 0,
            }),
            0,
            [],
        ),
        (
            1,
            0,
            0,
            True,
            RulesetConfig(scoring_tai={
                "base_tai": 2,
                "self_draw": 4,
                "in_hand": 5,
                "ping_hu": 6,
            }),
            17,
            [("底台", 2), ("自摸", 4), ("門清", 5), ("平胡", 6)],
        ),
        (
            0,
            0,
            2,
            False,
            RulesetConfig(scoring_tai={
                "base_tai": 2,
                "dealer_tai": 3,
                "in_hand": 5,
                "ping_hu": 6,
            }),
            18,
            [("底台", 2), ("莊家台", 3), ("連莊台", 2), ("門清", 5), ("平胡", 6)],
        ),
        (
            1,
            0,
            0,
            False,
            RulesetConfig(scoring_tai={"base_tai": 2}),
            4,
            [("底台", 2), ("門清", 1), ("平胡", 1)],
        ),
        (
            3,
            3,
            1,
            True,
            None,
            6,
            [
                ("底台", 1),
                ("自摸", 1),
                ("莊家台", 1),
                ("連莊台", 1),
                ("門清", 1),
                ("平胡", 1),
            ],
        ),
    ],
)
def test_fan_calculator_handles_common_and_configured_tai_combinations(
    winner_seat,
    dealer_seat,
    lian_zhuang,
    is_self_draw,
    config,
    expected_fans,
    expected_details,
):
    fans, details = FanCalculator().calculate(
        ALL_SEQUENCE_HAND,
        winner_seat=winner_seat,
        dealer_seat=dealer_seat,
        lian_zhuang=lian_zhuang,
        is_self_draw=is_self_draw,
        config=config,
    )

    assert fans == expected_fans
    assert details == expected_details


@pytest.mark.parametrize(
    "hand, melds, flowers, expected_fans, expected_details",
    [
        (
            [0, 1, 2, 9, 10, 11, 18, 19, 20, 27, 27, 27, 31, 31, 31, 33, 33],
            [],
            [],
            2,
            [("底台", 1), ("門清", 1)],
        ),
        (
            [0, 0, 0, 9, 9, 9, 18, 18, 18, 27, 27, 27, 31, 31, 31, 33, 33],
            [],
            [],
            2,
            [("底台", 1), ("門清", 1)],
        ),
        (
            ALL_SEQUENCE_HAND,
            [],
            [34],
            2,
            [("底台", 1), ("門清", 1)],
        ),
        (
            [3, 4, 5, 9, 10, 11, 18, 19, 20, 21, 22, 23, 24, 24],
            [Meld(meld_type=ActionType.CHI, tiles=[0, 1, 2], from_player=0)],
            [],
            2,
            [("底台", 1), ("平胡", 1)],
        ),
        (
            [3, 4, 5, 9, 10, 11, 18, 19, 20, 21, 22, 23, 24, 24],
            [Meld(meld_type=ActionType.PONG, tiles=[0, 0, 0], from_player=0)],
            [],
            1,
            [("底台", 1)],
        ),
        (
            [0, 1, 2, 3, 4, 5, 9, 10, 11, 18, 19, 20, 24, 24],
            [Meld(meld_type=ActionType.KONG, tiles=[27] * 4, from_player=1, kong_type="an")],
            [],
            2,
            [("底台", 1), ("門清", 1)],
        ),
        (
            [0, 1, 2, 3, 4, 5, 9, 10, 11, 18, 19, 20, 24, 24],
            [Meld(meld_type=ActionType.KONG, tiles=[27] * 4, from_player=1, kong_type="ming")],
            [],
            1,
            [("底台", 1)],
        ),
        (
            [0, 1, 2, 3, 4, 5, 9, 10, 11, 18, 19, 20, 24, 24],
            [Meld(meld_type=ActionType.KONG, tiles=[27] * 4, from_player=1, kong_type="jia")],
            [],
            1,
            [("底台", 1)],
        ),
        (
            [0, 0, 0, 3, 4, 5, 9, 10, 11, 18, 19, 20, 24, 24],
            [Meld(meld_type=ActionType.CHI, tiles=[0, 1, 2], from_player=0)],
            [],
            1,
            [("底台", 1)],
        ),
        (
            [0, 1, 2, 3, 4, 5, 9, 10, 11, 18, 19, 20, 27, 27, 27, 33, 33],
            [],
            [],
            2,
            [("底台", 1), ("門清", 1)],
        ),
    ],
)
def test_fan_calculator_handles_honors_triplets_flowers_and_meld_shapes(
    hand, melds, flowers, expected_fans, expected_details
):
    fans, details = FanCalculator().calculate(
        hand,
        winner_seat=1,
        dealer_seat=0,
        melds=melds,
        flowers=flowers,
    )

    assert fans == expected_fans
    assert details == expected_details


@pytest.mark.parametrize(
    "hand, meld_count, expected, error",
    [
        (ALL_SEQUENCE_HAND, 0, True, None),
        ([0, 1, 2, 3, 4, 5, 9, 10, 11, 18, 19, 20, 24, 24], 1, True, None),
        ([0, 1, 2, 9, 10, 11, 18, 19, 20, 24, 24], 2, True, None),
        (ALL_SEQUENCE_HAND[:-1], 0, False, None),
        ([tile for pair in range(7) for tile in (pair, pair)], 1, True, None),
        ([8, 9, 10, 9, 10, 11, 18, 19, 20, 27, 27, 27, 31, 31, 31, 33, 33], 0, False, None),
        ([0] * 5, 0, None, "Too many copies"),
        ([34], 0, None, "Invalid concealed hand tile ID"),
    ],
)
def test_basic_win_accepts_valid_shapes_and_rejects_invalid_ones(
    hand, meld_count, expected, error
):
    if error:
        with pytest.raises(ValueError, match=error):
            is_basic_win(hand, meld_count=meld_count)
    else:
        assert is_basic_win(hand, meld_count=meld_count) is expected


@pytest.mark.parametrize(
    "kwargs, message",
    [
        ({"winner_seat": -1, "dealer_seat": 0}, "between 0 and 3"),
        ({"winner_seat": 4, "dealer_seat": 0}, "between 0 and 3"),
        ({"winner_seat": True, "dealer_seat": 0}, "between 0 and 3"),
        ({"winner_seat": 0, "dealer_seat": -1}, "between 0 and 3"),
        ({"winner_seat": 0, "dealer_seat": 4}, "between 0 and 3"),
        ({"winner_seat": 0, "dealer_seat": False}, "between 0 and 3"),
        ({"winner_seat": 0, "dealer_seat": 1, "lian_zhuang": -1}, "non-negative integer"),
        ({"winner_seat": 0, "dealer_seat": 1, "lian_zhuang": True}, "non-negative integer"),
    ],
)
def test_fan_calculator_rejects_invalid_seats_and_consecutive_counts(kwargs, message):
    with pytest.raises(ValueError, match=message):
        FanCalculator().calculate(ALL_SEQUENCE_HAND, **kwargs)


@pytest.mark.parametrize(
    "points_per_fan",
    [0, -1, True],
)
def test_settlement_rejects_non_positive_or_non_integer_point_values(points_per_fan):
    with pytest.raises(ValueError, match="positive integer"):
        SettlementCalculator(points_per_fan=points_per_fan)


@pytest.mark.parametrize(
    "scores, total_fans, is_self_draw, message",
    [
        ({0: True, 1: 20000, 2: 20000, 3: 20000}, 1, True, "scores must be integers"),
        ({0: 20000, 1: 20000, 2: 20000, 3: 20000}, -1, True, "non-negative integer"),
    ],
)
def test_settlement_rejects_invalid_scores_and_fan_amounts(
    scores, total_fans, is_self_draw, message
):
    with pytest.raises(ValueError, match=message):
        SettlementCalculator().settle(
            scores,
            winner_seat=0,
            total_fans=total_fans,
            is_self_draw=is_self_draw,
        )
