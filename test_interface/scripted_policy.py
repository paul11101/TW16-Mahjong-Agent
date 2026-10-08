"""腳本化策略：指定要選哪個合法動作 id（測試反應流程用）。

BaselinePolicy 只會選胡／出牌／過，永遠不會選吃碰槓，所以測吃碰槓的點擊要用這個。
"""

from __future__ import annotations

from src.strategy.interfaces import Decision, LegalActions, Observation


class ScriptedPolicy:
    strategy_version = "scripted_v0"
    
    def __init__(self, action_id: str) -> None:
        self.action_id = action_id

    def decide(self, observation: Observation, legal_actions: LegalActions) -> Decision:
        for action in legal_actions:
            if action.id == self.action_id:
                return Decision(action=action, score=1.0, reason=f"scripted: {self.action_id}")

        raise ValueError(
            f"合法動作中沒有 {self.action_id}；可用：{[a.id for a in legal_actions]}"
        )