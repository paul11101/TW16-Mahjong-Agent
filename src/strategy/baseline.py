import random
from .interfaces import Decision, LegalActions, Observation
from src.common.schemas import ActionType
from .tile_efficiency import ShantenCalculator, evaluate_discard


# 隨機策略，只負責從合法動作中隨機選擇
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


# 基本策略，優先胡牌並使用向聽數與有效進張比較出牌
class BaselinePolicy:
    # calculator 可以傳入真正或假的向聽計算器
    # 沒有提供時維持原本的簡單 Baseline 行為
    def __init__(self, calculator: ShantenCalculator | None = None):
        self.calculator = calculator

    # 根據 Observation 與 LegalActions 選擇最終動作
    def decide(self, observation: Observation, legal_actions: LegalActions, ) -> Decision:
        # 沒有合法動作時無法做決策
        if not legal_actions:
            raise ValueError("legal_actions cannot be empty")

        # 如果目前可以胡牌，優先選擇 WIN
        for action in legal_actions:
            if action.action == ActionType.WIN:
                return Decision(action = action, score = 1.0, reason = "win is available", )

        # 從所有合法動作中找出 DISCARD
        discard_actions = [action for action in legal_actions if action.action == ActionType.DISCARD]

        # 有合法棄牌而且有提供向聽計算器時，使用牌效率比較
        if discard_actions and self.calculator is not None:
            # 儲存目前找到的最佳棄牌
            best_action = None

            # 儲存最佳棄牌的向聽數
            best_shanten = None

            # 儲存最佳棄牌的有效進張種類數
            best_effective_count = -1

            # 逐一評估每個合法棄牌
            for action in discard_actions:
                # 計算打出這張牌之後的向聽數與有效進張
                shanten, draws = evaluate_discard(observation.hand, action.tile, self.calculator,)

                # 使用有效進張的種類數作為第二順位比較條件
                effective_count = len(draws)

                # 優先選擇向聽數較低的出牌
                # 如果向聽數相同，再選有效進張種類較多的出牌
                if (best_action is None or shanten < best_shanten or (shanten == best_shanten and effective_count > best_effective_count)):
                    best_action = action
                    best_shanten = shanten
                    best_effective_count = effective_count

            # 回傳目前找到的最佳棄牌
            # score 使用負向聽數，向聽越低代表分數越高
            return Decision(action = best_action, score = float(-best_shanten), reason = (f"shanten = {best_shanten}, " f"effective_draws = {best_effective_count}"), )

        # 如果沒有提供向聽計算器，就維持原本 Baseline
        # 直接選擇第一個合法棄牌
        if discard_actions:
            return Decision(action = discard_actions[0], score = 0.0, reason = "baseline discard",)

        # 如果不能棄牌但有 PASS，就選擇 PASS
        for action in legal_actions:
            if action.action == ActionType.PASS:
                return Decision(action = action, score = 0.0, reason = "baseline pass",)

        # 如果以上條件都沒有符合，就使用第一個合法動作作為保底
        return Decision(action = legal_actions[0], score = 0.0, reason = "fallback legal action",)