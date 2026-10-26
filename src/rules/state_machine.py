"""整局麻將流程的明確階段與轉換。"""

from enum import Enum
from random import Random
from typing import Optional, Sequence

from .game_state import GameState
from .rule import RulesetConfig


class GameStage(str, Enum):
    INIT_ROUND = "init_round"
    PLAYER_TURN = "player_turn"
    CLAIM_PHASE = "claim_phase"
    SETTLEMENT = "settlement"
    ROUND_END = "round_end"


class MahjongStateMachine:
    """協調發牌、回合、反應、結算與下一局初始化。"""

    def __init__(
        self,
        state: GameState,
        config: Optional[RulesetConfig] = None,
        rng: Optional[Random] = None,
    ) -> None:
        self.state = state
        self.config = config or RulesetConfig()
        self.rng = rng
        self.stage = GameStage.INIT_ROUND

    def start_round(self) -> None:
        if self.stage != GameStage.INIT_ROUND:
            raise ValueError(f"Cannot initialize a round from stage {self.stage.value}")

        if self.state.is_over:
            self.state.next_round(config=self.config, rng=self.rng)
        else:
            self.state.deal(config=self.config)
        self.stage = GameStage.PLAYER_TURN

    def begin_claim_phase(self) -> None:
        self._transition(GameStage.PLAYER_TURN, GameStage.CLAIM_PHASE)

    def resume_player_turn(self) -> None:
        self._transition(GameStage.CLAIM_PHASE, GameStage.PLAYER_TURN)

    def begin_settlement(self) -> None:
        if self.stage not in (GameStage.PLAYER_TURN, GameStage.CLAIM_PHASE):
            raise ValueError(f"Cannot settle a round from stage {self.stage.value}")
        self.stage = GameStage.SETTLEMENT

    def process_round_end(
        self,
        winner_seats: Sequence[int] = (),
        is_draw: Optional[bool] = None,
    ) -> None:
        if self.stage != GameStage.SETTLEMENT:
            raise ValueError("Round end can only be processed from settlement stage")

        winners = list(winner_seats)
        draw_result = not winners if is_draw is None else is_draw
        if not isinstance(draw_result, bool) or draw_result != (not winners):
            raise ValueError("A drawn round must have no winners; a win must have at least one")
        if self.state.is_over:
            if not draw_result:
                raise ValueError("The round was already completed before winner settlement")
        else:
            self.state.complete_round(winner_seats=winners, is_draw=draw_result)
        self.stage = GameStage.ROUND_END
        self.stage = GameStage.INIT_ROUND
        self.start_round()

    def _transition(self, expected: GameStage, target: GameStage) -> None:
        if self.stage != expected:
            raise ValueError(
                f"Cannot transition from {self.stage.value}; expected {expected.value}"
            )
        self.stage = target
