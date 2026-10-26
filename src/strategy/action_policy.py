from src.common.schemas import ActionType
from .baseline import BaselineV05Policy
from .interfaces import Decision, LegalActions, Observation
from .kong_policy import KongEfficiencyPolicy
from .meld_policy import MeldShantenCalculator
from .candidate_scoring import CandidateEvaluation, score_candidates


# 定義策略模組可以處理的六種合法動作
# 摸牌、補花等遊戲事件不在此策略的決策範圍內
SUPPORTED_ACTIONS = frozenset({
    ActionType.WIN,
    ActionType.DISCARD,
    ActionType.CHI,
    ActionType.PONG,
    ActionType.KONG,
    ActionType.PASS,
})


# 統一策略入口，負責整合胡牌、吃碰槓、過牌及棄牌決策
class ActionPolicy:
    strategy_version = "action_policy"

    def __init__(self):
        # 沿用原本的槓牌策略
        # 此策略也會處理吃、碰與 PASS 的判斷
        self.reaction_policy = KongEfficiencyPolicy()

        # 取得全部候選評分，不改變 decide() 的選牌流程

    def score_candidates(
            self,
            observation: Observation,
            legal_actions: LegalActions,
    ) -> tuple[CandidateEvaluation, ...]:
        return score_candidates(
            observation,
            legal_actions,
        )

    # 根據目前可見的牌局資訊及合法動作，選擇最適合的行動
    def decide(self, observation: Observation, legal_actions: LegalActions) -> Decision:
        # 將合法動作轉成 tuple，避免修改原本的動作清單
        actions = tuple(legal_actions)

        # 沒有任何合法動作時，直接回報錯誤
        if not actions:
            raise ValueError("legal_actions cannot be empty")

        # 確認所有候選動作都屬於策略支援的六種動作
        # 避免將未知的動作當成一般出牌執行
        for action in actions:
            if action.action not in SUPPORTED_ACTIONS:
                raise ValueError(f"unsupported decision action: {action.action}")

        # 胡牌具有最高優先順序
        # 只要 Rules 提供合法 WIN，就直接選擇胡牌
        for action in actions:
            if action.action == ActionType.WIN:
                return Decision(action = action, score = 1.0, reason = "win is available")

        # 確認公開副露資料包含四位玩家
        if len(observation.melds) != 4:
            raise ValueError("melds must contain four players")

        # 確認 Agent 自己的座位編號位於 0~3
        if not 0 <= observation.seat < 4:
            raise ValueError("invalid player seat")

        # 從合法動作中取出所有棄牌選項
        discard_actions = [
            action for action in actions
            if action.action == ActionType.DISCARD
        ]

        # 檢查目前是否存在吃、碰或槓的合法動作
        has_meld_action = any(
            action.action in (ActionType.CHI, ActionType.PONG, ActionType.KONG)
            for action in actions
        )

        # 如果可以吃、碰或槓，就先交給原本的副露策略判斷
        if has_meld_action:
            # 沿用既有策略，評估是否值得進行吃、碰或槓
            decision = self.reaction_policy.decide(observation, actions)

            # 確認子策略選出的動作存在於合法動作清單中
            self._check_legal_decision(decision, actions)

            # 如果結果不是棄牌，就直接採用原本的決策
            # 例如吃、碰、槓或 PASS
            if decision.action.action != ActionType.DISCARD:
                return decision

        # 如果目前存在合法棄牌，就使用牌效率策略選牌
        if discard_actions:
            # 取得自己已經完成的副露組數
            meld_count = len(observation.melds[observation.seat])

            # 根據副露組數建立向聽計算器
            # 避免已經完成的副露被重複計算
            calculator = MeldShantenCalculator(meld_count)

            # 沿用既有的公開資訊棄牌策略
            # 比較向聽數、有效進張及未見牌數上限
            discard_policy = BaselineV05Policy(calculator)

            # 從合法棄牌選項中找出最適合打出的牌
            decision = discard_policy.decide(observation, discard_actions)

            # 確認最後選出的棄牌動作合法，再回傳結果
            return self._check_legal_decision(decision, actions)

        # 如果沒有合法棄牌，檢查是否可以選擇 PASS
        for action in actions:
            if action.action == ActionType.PASS:
                return Decision(action = action, score = 0.0, reason = "only pass is available")

        # 沒有能安全執行的動作時，不強制選擇其他動作
        raise ValueError("no safe legal action available")

    # 統一檢查策略回傳的決策是否符合 Rules 提供的合法動作
    @staticmethod
    def _check_legal_decision(decision: Decision, legal_actions: LegalActions) -> Decision:
        # 如果選出的動作不在合法清單內，就拒絕該決策
        if decision.action not in legal_actions:
            raise ValueError("policy selected an action outside legal_actions")

        # 確認合法後，回傳原本的決策結果
        return decision