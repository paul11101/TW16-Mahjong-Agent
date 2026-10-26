import random

from src.common.schemas import ActionType

from .interfaces import Decision, LegalActions, Observation
from .public_features import extract_public_features
from .tile_efficiency import (
    ShantenCalculator,
    iter_best_discard_evaluations,
)


# 隨機策略，只負責從合法動作中隨機選擇
class RandomPolicy:
    def decide(
        self,
        observation: Observation,
        legal_actions: LegalActions,
    ) -> Decision:
        if not legal_actions:
            raise ValueError("legal_actions cannot be empty")

        action = random.choice(legal_actions)

        return Decision(
            action=action,
            score=0.0,
            reason="random legal action",
        )


# 基本策略，優先胡牌並使用牌效率比較出牌
class BaselinePolicy:
    def __init__(
        self,
        calculator: ShantenCalculator | None = None,
    ):
        # 可以傳入正式或測試用的向聽計算器
        self.calculator = calculator

    # 提供子類別擴充公開資訊的入口
    def _unseen_upper_bounds(
        self,
        observation: Observation,
    ) -> tuple[int, ...] | None:
        # 基本策略不使用公開張數加權
        return None

    def decide(
        self,
        observation: Observation,
        legal_actions: LegalActions,
    ) -> Decision:
        if not legal_actions:
            raise ValueError("legal_actions cannot be empty")

        # 如果 Rules 提供合法胡牌，優先選擇 WIN
        for action in legal_actions:
            if action.action == ActionType.WIN:
                return Decision(
                    action=action,
                    score=1.0,
                    reason="win is available",
                )

        # 從合法動作中取出所有棄牌選項
        discard_actions = [
            action
            for action in legal_actions
            if action.action == ActionType.DISCARD
        ]

        # 有合法棄牌及向聽計算器時，使用牌效率比較
        if discard_actions and self.calculator is not None:
            # 每次決策只取得一次公開資訊
            unseen = self._unseen_upper_bounds(observation)

            best_quality = None
            best = None

            # 沿用共用流程，只評估最低向聽候選的有效進張
            for tile, shanten, draws in iter_best_discard_evaluations(
                observation.hand,
                (action.tile for action in discard_actions),
                self.calculator,
            ):
                # 使用公開資訊時，排除已經全部可見的牌種
                available = (
                    draws
                    if unseen is None
                    else tuple(
                        draw
                        for draw in draws
                        if unseen[draw] > 0
                    )
                )

                effective_count = len(available)

                # 基本策略固定使用 0，因此只比較有效進張種類數
                unseen_count = (
                    0
                    if unseen is None
                    else sum(unseen[draw] for draw in available)
                )

                # 先比較未見張數上限，再比較有效進張種類數
                quality = (unseen_count, effective_count)

                # 完全平手時，保留原本合法動作的順序
                if best_quality is None or quality > best_quality:
                    best_quality = quality
                    best = (
                        tile,
                        shanten,
                        effective_count,
                        unseen_count,
                    )

            assert best is not None
            tile, shanten, effective_count, unseen_count = best

            # 相同牌種有不同動作 ID 時，取原清單中的第一個
            action = next(
                action
                for action in discard_actions
                if action.tile == tile
            )

            reason = (
                f"shanten = {shanten}, "
                f"effective_draws = {effective_count}"
            )

            # 有使用公開資訊時，補上未見張數上限
            if unseen is not None:
                reason += f", unseen_upper_bound = {unseen_count}"

            return Decision(
                action=action,
                score=float(-shanten),
                reason=reason,
            )

        # 沒有向聽計算器時，維持原本的第一個合法棄牌
        if discard_actions:
            return Decision(
                action=discard_actions[0],
                score=0.0,
                reason="baseline discard",
            )

        # 不能棄牌但有 PASS 時，選擇 PASS
        for action in legal_actions:
            if action.action == ActionType.PASS:
                return Decision(
                    action=action,
                    score=0.0,
                    reason="baseline pass",
                )

        # 沿用原本保底行為，選擇第一個合法動作
        return Decision(
            action=legal_actions[0],
            score=0.0,
            reason="fallback legal action",
        )


# 公開資訊策略，共用 Baseline 的決策流程
class BaselineV05Policy(BaselinePolicy):
    strategy_version = "baseline_v0.5"

    # 只提供公開資訊，不重寫整個 decide()
    def _unseen_upper_bounds(
        self,
        observation: Observation,
    ) -> tuple[int, ...] | None:
        return extract_public_features(observation).unseen_upper_bounds