from collections.abc import Callable
from dataclasses import dataclass, replace
from math import isfinite

from src.common.schemas import ActionType
from .action_policy import ActionPolicy
from .interfaces import Decision, LegalActions, Observation

ChangeHandler = Callable[[Observation, LegalActions, Decision, Decision], None]


@dataclass(frozen=True)
class DiscardWeights:
    unseen: float = 1.0
    effective: float = 0.0

    def __post_init__(self):
        values = (self.unseen, self.effective)
        if any(type(v) not in (int, float) or not isfinite(v) or v < 0 for v in values):
            raise ValueError("weights must be finite and non-negative")
        if not any(values):
            raise ValueError("at least one weight must be positive")


# 只調整同向聽的棄牌排序，其他動作沿用 Baseline v1
class WeightedPolicy:
    strategy_version = "baseline_weighted_v1"

    def __init__(self, weights: DiscardWeights = DiscardWeights(), *,
                 on_change: ChangeHandler | None = None):
        self.weights = weights
        self.on_change = on_change
        self.base = ActionPolicy()

    def decide(self, observation: Observation, legal_actions: LegalActions) -> Decision:
        actions = tuple(legal_actions)
        original = self.base.decide(observation, actions)
        if original.action.action != ActionType.DISCARD:
            return original

        # 重用既有候選明細，不重寫向聽與進張計算
        scores = {item.action_id: item for item in original.candidate_evaluations}
        candidates = [action for action in actions if action.action == ActionType.DISCARD]
        for action in candidates:
            item = scores.get(action.id)
            if item is None or not item.scorable or any(value is None for value in (
                item.shanten, item.unseen_upper_bound, item.effective_draws,
            )):
                raise ValueError(f"cannot tune unscorable discard: {action.id}")

        def rank(action):
            item = scores[action.id]
            value = (self.weights.unseen * item.unseen_upper_bound
                     + self.weights.effective * item.effective_draws)
            return -item.shanten, value, item.unseen_upper_bound, item.effective_draws

        # 先比向聽，再比加權值；完全相同時保留合法動作順序
        selected = max(candidates, key=rank)
        if selected == original.action:
            return original

        item = scores[selected.id]
        decision = replace(
            original, action=selected, score=float(-item.shanten),
            reason=f"{item.reason}, weighted_value = {rank(selected)[1]:g}",
        )
        if self.on_change is not None:
            self.on_change(observation, actions, original, decision)
        return decision