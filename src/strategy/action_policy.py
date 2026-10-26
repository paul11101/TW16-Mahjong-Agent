from dataclasses import replace

from src.common.schemas import ActionType
from .baseline import BaselineV05Policy
from .candidate_scoring import score_candidates
from .interfaces import CandidateEvaluation, Decision, LegalActions, Observation
from .kong_policy import KongEfficiencyPolicy
from .meld_policy import MeldShantenCalculator

SUPPORTED_ACTIONS = frozenset({
    ActionType.WIN, ActionType.DISCARD, ActionType.CHI,
    ActionType.PONG, ActionType.KONG, ActionType.PASS,
})


class ActionPolicy:
    strategy_version = "action_policy"

    def __init__(self, *, include_candidate_scores: bool = True):
        self.reaction_policy = KongEfficiencyPolicy()
        self.include_candidate_scores = include_candidate_scores

    def score_candidates(self, observation: Observation,
                         legal_actions: LegalActions) -> tuple[CandidateEvaluation, ...]:
        return score_candidates(observation, legal_actions)

    # 先沿用原本決策，再附上候選資訊，不改成選擇最高分
    def decide(self, observation: Observation, legal_actions: LegalActions) -> Decision:
        actions = tuple(legal_actions)
        decision = self._select_action(observation, actions)
        if not self.include_candidate_scores:
            return decision
        evaluations = self.score_candidates(observation, actions)
        return replace(decision, candidate_evaluations=evaluations)

    # 保留 Day 2 的選牌順序與比較規則
    def _select_action(self, observation: Observation, legal_actions: LegalActions) -> Decision:
        actions = tuple(legal_actions)
        if not actions:
            raise ValueError("legal_actions cannot be empty")
        for action in actions:
            if action.action not in SUPPORTED_ACTIONS:
                raise ValueError(f"unsupported decision action: {action.action}")

        for action in actions:
            if action.action == ActionType.WIN:
                return Decision(action=action, score=1.0, reason="win is available")

        if len(observation.melds) != 4:
            raise ValueError("melds must contain four players")
        if not 0 <= observation.seat < 4:
            raise ValueError("invalid player seat")

        discard_actions = [a for a in actions if a.action == ActionType.DISCARD]
        has_meld_action = any(
            a.action in (ActionType.CHI, ActionType.PONG, ActionType.KONG) for a in actions
        )

        # 吃碰槓與 PASS 繼續交給既有反應策略
        if has_meld_action:
            decision = self.reaction_policy.decide(observation, actions)
            self._check_legal_decision(decision, actions)
            if decision.action.action != ActionType.DISCARD:
                return decision

        # 棄牌繼續使用公開資訊 Baseline
        if discard_actions:
            calculator = MeldShantenCalculator(len(observation.melds[observation.seat]))
            decision = BaselineV05Policy(calculator).decide(observation, discard_actions)
            return self._check_legal_decision(decision, actions)

        for action in actions:
            if action.action == ActionType.PASS:
                return Decision(action=action, score=0.0, reason="only pass is available")
        raise ValueError("no safe legal action available")

    @staticmethod
    def _check_legal_decision(decision: Decision, legal_actions: LegalActions) -> Decision:
        if decision.action not in legal_actions:
            raise ValueError("policy selected an action outside legal_actions")
        return decision