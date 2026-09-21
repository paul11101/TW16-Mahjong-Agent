import random
from .interfaces import Decision, LegalActions, Observation


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


from .interfaces import ActionType, Decision, LegalActions, Observation


class BaselinePolicy:
    # 使用固定優先順序選擇動作
    def decide(self, observation: Observation, legal_actions: LegalActions, ) -> Decision:
        # 沒有合法動作時無法做決策
        if not legal_actions:
            raise ValueError("legal_actions cannot be empty")

        # 若可以胡牌，優先選擇 WIN
        for action in legal_actions:
            if action.action == ActionType.WIN:
                return Decision(action=action, score=1.0, reason="win is available", )

        # 若不能胡牌，先選擇第一個合法的出牌動作
        for action in legal_actions:
            if action.action == ActionType.DISCARD:
                return Decision(action=action, score=0.0, reason="baseline discard", )

        # 若沒有出牌動作但可以 PASS，則選擇 PASS
        for action in legal_actions:
            if action.action == ActionType.PASS:
                return Decision(action=action, score=0.0, reason="baseline pass", )

        # 以上都沒有時，使用第一個合法動作作為保底
        return Decision(action=legal_actions[0], score=0.0, reason="fallback legal action", )