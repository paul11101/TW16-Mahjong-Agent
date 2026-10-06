import random
from .interfaces import Decision, LegalActions, Observation
from src.common.schemas import ActionType
from .tile_efficiency import ShantenCalculator, evaluate_discard

class RandomPolicy:
    # 從所有合法動作中隨機選擇一個
    def decide(self, observation: Observation, legal_actions: LegalActions, ) -> Decision:
        # 沒有合法動作時無法做決策
        if not legal_actions:
            raise ValueError("legal_actions cannot be empty")

        # 隨機選擇一個合法動作
        action = random.choice(legal_actions)

        # 回傳決策結果
        return Decision(action=action, score=0.0, reason="random legal action", )


class BaselinePolicy:
    def __init__(self, calculator: ShantenCalculator | None = None):
        self.calculator = calculator


    def decide(self, observation: Observation, legal_actions: LegalActions, ) -> Decision:
        if not legal_actions:
            raise ValueError("legal_actions cannot be empty")

        for action in legal_actions:
            if action.action == ActionType.WIN:
                return Decision(action = action, score = 1.0, reason = "win is available", )

        discard_actions = [action for action in legal_actions if action.action == ActionType.DISCARD]

        if discard_actions and self.calculator is not None:
            best_action = None
            best_shanten = None
            best_effective_count = -1

            for action in discard_actions:
                shanten, draws = evaluate_discard(observation.hand, action.tile, self.calculator,)
                effective_count = len(draws)

                if (best_action is None or shanten < best_shanten or (shanten == best_shanten and effective_count > best_effective_count)):
                    best_action = action
                    best_shanten = shanten
                    best_effective_count = effective_count

            return Decision(action = best_action, score = float(-best_shanten), reason = (f"shanten = {best_shanten}, " f"effective_draws = {best_effective_count}"), )

        if discard_actions:
            return Decision(action = discard_actions[0], score = 0.0, reason = "baseline discard",)

        for action in legal_actions:
            if action.action == ActionType.PASS:
                return Decision(action = action, score = 0.0, reason = "baseline pass",)

        return Decision(action = legal_actions[0], score = 0.0, reason = "fallback legal action",)