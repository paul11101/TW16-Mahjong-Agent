from dataclasses import dataclass
from typing import Protocol, Sequence

from src.common.schemas import ActionType, CandidateScore

Tile = int


# 策略只接收自己的手牌與公開資訊
@dataclass(frozen=True)
class Observation:
    hand: tuple[Tile, ...]
    discards: tuple[tuple[Tile, ...], ...]
    melds: tuple[tuple[tuple[Tile, ...], ...], ...]
    flowers: tuple[tuple[Tile, ...], ...]
    current_player: int
    seat: int
    remaining_tiles: int | None = None


# Rules 提供的單一合法動作
@dataclass(frozen=True)
class LegalAction:
    id: str
    action: ActionType
    tile: Tile | None = None
    tiles: tuple[Tile, ...] = ()
    kong_type: str | None = None


LegalActions = Sequence[LegalAction]


# 從 candidate_scoring 移到共用介面，避免循環匯入
@dataclass(frozen=True)
class CandidateEvaluation:
    action_id: str
    score: float | None = None
    shanten: int | None = None
    effective_draws: int | None = None
    unseen_upper_bound: int | None = None
    next_discard: Tile | None = None
    scorable: bool = False
    reason: str = ""

    def to_candidate_score(self) -> CandidateScore | None:
        if not self.scorable or self.score is None:
            return None
        return CandidateScore(action_id=self.action_id, score=self.score, reason=self.reason)


# 新欄位有預設值，原本三個參數的建構方式仍可使用
@dataclass(frozen=True)
class Decision:
    action: LegalAction
    score: float
    reason: str
    candidate_evaluations: tuple[CandidateEvaluation, ...] = ()

    # 共用分數由診斷資料轉換，不另外保存一份重複資料
    @property
    def candidate_scores(self) -> tuple[CandidateScore, ...]:
        scores = (item.to_candidate_score() for item in self.candidate_evaluations)
        return tuple(score for score in scores if score is not None)


class Strategy(Protocol):
    def decide(self, observation: Observation, legal_actions: LegalActions) -> Decision:
        ...