import json

import pytest

from src.rules.game_result import (
    GameResultPresenter,
    WinType,
    WinnerFanResult,
    print_game_summary,
    print_round_summary,
)
from src.rules.game_state import GameState, PlayerState


def make_state(*, dealer=0, round_wind=0, lian_zhuang=1, scores=None):
    scores = scores or {0: 21000, 1: 19700, 2: 20000, 3: 19300}
    return GameState(
        game_id="result-test",
        dealer=dealer,
        round_wind=round_wind,
        lian_zhuang=lian_zhuang,
        players={
            seat: PlayerState(seat_id=seat, score=scores[seat])
            for seat in range(4)
        },
    )


def test_result_captures_win_details_score_deltas_and_serializes_json():
    scores_before = {0: 20000, 1: 20000, 2: 20000, 3: 20000}
    state = make_state(scores={0: 19600, 1: 21200, 2: 19600, 3: 19600})

    result = GameResultPresenter.create_result(
        state,
        round_number=1,
        scores_before=scores_before,
        winner_seats=[1],
        win_type=WinType.SELF_DRAW,
        total_fans=4,
        fan_details=[("底台", 1), ("自摸", 1), ("門清", 1), ("平胡", 1)],
    )

    assert result.round_label == "東風場第 1 局"
    assert result.dealer_seat == 0
    assert result.winner_seats == (1,)
    assert result.loser_seat is None
    assert result.total_fans == 4
    assert result.fan_details[-1] == ("平胡", 1)
    assert result.score_delta == {0: -400, 1: 1200, 2: -400, 3: -400}
    assert result.scores_dict == {0: 19600, 1: 21200, 2: 19600, 3: 19600}

    data = json.loads(result.to_json())
    assert data["round_label"] == "東風場第 1 局"
    assert data["total_fans"] == 4
    assert data["winner_fan_results"]["1"]["total_fans"] == 4
    assert data["score_delta"]["1"] == 1200


def test_multi_win_keeps_fan_details_per_winner():
    state = make_state()

    result = GameResultPresenter.create_result(
        state,
        round_number=7,
        scores_before={seat: 20000 for seat in range(4)},
        winner_seats=[1, 2],
        loser_seat=0,
        win_type=WinType.DISCARD_WIN,
        winner_fan_results={
            1: (3, [("底台", 1), ("門清", 1), ("平胡", 1)]),
            2: WinnerFanResult(2, 5, (("底台", 1), ("自摸", 0), ("清一色", 4))),
        },
    )

    assert result.total_fans is None
    assert result.winner_fan_results[1].total_fans == 3
    assert result.winner_fan_results[2].total_fans == 5
    assert result.to_dict()["total_fans"] is None


def test_draw_result_has_no_winner_or_fan_and_prints_summary(capsys):
    state = make_state(round_wind=1)
    result = GameResultPresenter.create_result(
        state,
        round_number=3,
        scores_before={seat: 20000 for seat in range(4)},
        win_type=WinType.DRAW,
    )

    print_round_summary(result)

    output = capsys.readouterr().out
    assert "南風場第 3 局" in output
    assert "荒牌流局" in output
    assert "座位 0：+0 → 20000" in output
    assert result.winner_seats == ()
    assert result.total_fans is None
    assert result.score_delta == {seat: 0 for seat in range(4)}
    assert result.scores_dict == {seat: 20000 for seat in range(4)}
    assert all(f"座位 {seat}：+0 → 20000" in output for seat in range(4))


def test_game_summary_aggregates_rounds_and_final_scores(capsys):
    first_state = make_state(scores={0: 19600, 1: 21200, 2: 19600, 3: 19600})
    first_result = GameResultPresenter.create_result(
        first_state,
        round_number=1,
        scores_before={seat: 20000 for seat in range(4)},
        winner_seats=[1],
        win_type=WinType.SELF_DRAW,
        total_fans=4,
        fan_details=[("底台", 1), ("自摸", 1), ("門清", 1), ("平胡", 1)],
    )
    draw_state = make_state(scores={0: 19600, 1: 21200, 2: 19600, 3: 19600})
    draw_result = GameResultPresenter.create_result(
        draw_state,
        round_number=2,
        scores_before={0: 19600, 1: 21200, 2: 19600, 3: 19600},
        win_type=WinType.DRAW,
    )

    summary = GameResultPresenter.create_game_summary([first_result, draw_result])
    print_game_summary(summary)

    assert summary.winner_counts == {0: 0, 1: 1, 2: 0, 3: 0}
    assert summary.draw_count == 1
    assert summary.final_scores == dict(draw_result.scores_dict)
    assert json.loads(summary.to_json())["round_count"] == 2
    assert "共 2 局，流局 1 局" in capsys.readouterr().out


@pytest.mark.parametrize(
    "kwargs, message",
    [
        (
            {"winner_seats": [1], "win_type": WinType.DRAW},
            "cannot have winners",
        ),
        (
            {"winner_seats": [], "win_type": WinType.SELF_DRAW},
            "must include at least one winner",
        ),
        (
            {
                "winner_seats": [1, 2],
                "loser_seat": 0,
                "win_type": WinType.DISCARD_WIN,
                "total_fans": 1,
            },
            "winner_fan_results to provide per-winner fans",
        ),
        (
            {
                "winner_seats": [1],
                "win_type": WinType.SELF_DRAW,
                "total_fans": 1,
                "fan_details": [("底台", 2)],
            },
            "Fan details must sum",
        ),
    ],
)
def test_invalid_result_combinations_are_rejected(kwargs, message):
    base = {
        "round_number": 1,
        "scores_before": {seat: 20000 for seat in range(4)},
    }
    base.update(kwargs)

    with pytest.raises(ValueError, match=message):
        GameResultPresenter.create_result(make_state(), **base)
