from dataclasses import replace

import pytest

from src.rules.game_result import GameResultPresenter, WinType
from src.rules.game_state import GameState, PlayerState
from src.rules.settlement_calculator import SettlementCalculator
from src.strategy.evaluation_metrics import EvaluationRecord, summarize_evaluation
from src.strategy.evaluation_plan import EvaluationGame


# 測試結果也使用 Rules 結算，避免在測試內重寫計分規則
def make_record(seed, seat, win_type=WinType.DRAW, *, winners=(), loser=None):
    before = dict.fromkeys(range(4), 20000)
    scores = before.copy()
    for winner in winners:
        scores = SettlementCalculator().settle(
            scores, winner_seat=winner, total_fans=1,
            is_self_draw=win_type == WinType.SELF_DRAW, loser_seat=loser,
        )
    state = GameState(
        game_id=f"metrics_{seed}_{seat}", dealer=0, wall=[],
        players={i: PlayerState(seat_id=i, score=scores[i]) for i in range(4)},
    )
    result = GameResultPresenter.create_result(
        state, round_number=1, scores_before=before, win_type=win_type,
        winner_seats=winners, loser_seat=loser,
        winner_fan_results={i: (1, (("測試台", 1),)) for i in winners},
    )
    return EvaluationRecord(EvaluationGame(seed, seat), result)


# 混合自摸、胡牌、一炮多響、他家自摸與流局
def test_mixed_results_use_all_completed_games():
    records = [
        make_record(0, 2, WinType.SELF_DRAW, winners=(2,)),
        make_record(1, 1, WinType.DISCARD_WIN, winners=(1,), loser=3),
        make_record(2, 3, WinType.DISCARD_WIN, winners=(0, 1), loser=3),
        make_record(3, 0, WinType.SELF_DRAW, winners=(2,)),
        make_record(4, 1),
    ]
    assert summarize_evaluation(records) == {
        "games": 5, "wins": 2, "deal_ins": 1, "draws": 1,
        "total_score": 100, "mean_score": 20.0,
        "win_rate": 0.4, "deal_in_rate": 0.2,
    }


# 同一牌山的四個受測座位是四筆不同設定
def test_rotating_seats_use_the_correct_player():
    records = [
        make_record(7, seat, WinType.SELF_DRAW, winners=(2,))
        for seat in range(4)
    ]
    summary = summarize_evaluation(records)
    assert summary["games"] == 4
    assert summary["mean_score"] == 0
    assert summary["win_rate"] == 0.25
    assert summary["deal_in_rate"] == 0


# 多響時每位胡家各算一勝，放槍者只算一次，其餘玩家不受影響
@pytest.mark.parametrize("seat, score, wins, deals", [
    (0, 100, 1, 0), (1, 100, 1, 0), (2, -200, 0, 1), (3, 0, 0, 0),
])
def test_multi_win_counts_once_per_player(seat, score, wins, deals):
    record = make_record(0, seat, WinType.DISCARD_WIN, winners=(0, 1), loser=2)
    summary = summarize_evaluation([record])
    assert summary["mean_score"] == score
    assert summary["wins"] == wins
    assert summary["deal_ins"] == deals
    assert summary["draws"] == 0


# 全部流局仍有有效樣本，三項指標皆為零
def test_all_draws_are_counted():
    summary = summarize_evaluation([make_record(seed, 0) for seed in range(3)])
    assert summary["games"] == summary["draws"] == 3
    assert summary["mean_score"] == summary["win_rate"] == summary["deal_in_rate"] == 0


# 平均得分保留負值，不取絕對值或截成零
def test_negative_mean_score():
    summary = summarize_evaluation([
        make_record(0, 0, WinType.SELF_DRAW, winners=(1,)),
        make_record(1, 0, WinType.DISCARD_WIN, winners=(1, 2), loser=0),
    ])
    assert summary["mean_score"] == -150
    assert summary["deal_in_rate"] == 0.5


# 空資料不能回報零勝率；同一評測設定不能重複納入
def test_empty_and_duplicate_records_are_rejected():
    with pytest.raises(ValueError, match="empty"):
        summarize_evaluation([])
    with pytest.raises(ValueError, match="unique"):
        summarize_evaluation([make_record(0, 0), make_record(0, 0)])


# 結果必須來自評測指定的莊家設定
def test_mismatched_dealer_is_rejected():
    record = make_record(0, 0)
    with pytest.raises(ValueError, match="dealer"):
        replace(record, result=replace(record.result, dealer_seat=1))