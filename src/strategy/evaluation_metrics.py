from dataclasses import dataclass
from typing import Sequence

from src.rules.game_result import GameResult, WinType
from .evaluation_plan import EvaluationGame

# 配對固定評測設定與 Rules 的單局結算結果
@dataclass(frozen=True)
class EvaluationRecord:
    game: EvaluationGame
    result: GameResult

    # 確認結算結果的莊家與評測設定一致
    def __post_init__(self):
        if self.result.dealer_seat != self.game.dealer:
            raise ValueError("result dealer does not match evaluation game")




# 每次統計同一受測策略，只接收已完成結算的牌局
def summarize_evaluation(records: Sequence[EvaluationRecord]) -> dict[str, int | float]:
    records = tuple(records)
    # 拒絕空資料與重複設定，避免誤報零勝率或重複計數
    if not records:
        raise ValueError("records cannot be empty")
    if len({record.game for record in records}) != len(records):
        raise ValueError("evaluation games must be unique")

    total_score = wins = deal_ins = draws = 0
    for record in records:
        seat, result = record.game.agent_seat, record.result
        # 累計受測座位的增減分，不使用起始總分或候選動作評分
        total_score += result.score_delta[seat]
        # 胡牌包含自摸與他家放槍，多響時每位胡家各算一勝
        wins += int(seat in result.winner_seats)
        draws += int(result.win_type == WinType.DRAW)
        # 一炮多響只計一次放槍；支付他家自摸不算放槍
        deal_ins += int(result.win_type == WinType.DISCARD_WIN and result.loser_seat == seat)

    # 分母包含流局，執行失敗不能當成零分流局
    games = len(records)
    return {
        "games": games,
        "wins": wins,
        "deal_ins": deal_ins,
        "draws": draws,
        "total_score": total_score,
        "mean_score": total_score / games,
        "win_rate": wins / games,
        "deal_in_rate": deal_ins / games,
    }