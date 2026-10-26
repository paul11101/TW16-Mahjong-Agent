from src.common.schemas import ActionType

from .baseline import BaselinePolicy
from .interfaces import (
    Decision,
    LegalAction,
    LegalActions,
    Observation,
    Tile,
)
from .shanten import Taiwan16ShantenCalculator
from .tile_efficiency import iter_best_discard_evaluations


# 副露後的向聽計算器，沿用台灣 16 張向聽演算法
class MeldShantenCalculator(Taiwan16ShantenCalculator):
    def __init__(self, meld_count: int):
        if not 0 <= meld_count <= 5:
            raise ValueError("meld_count must be between 0 and 5")

        # 扣除已完成的副露，只計算剩餘需要完成的面子
        self.MAX_MELDS = 5 - meld_count


# 模擬吃牌或碰牌，計算副露後剩下的暗牌
def simulate_meld(
    hand: tuple[Tile, ...],
    action: LegalAction,
) -> tuple[Tile, ...]:
    if action.tile is None or not 0 <= action.tile < 34:
        raise ValueError("invalid meld target")

    # 吃牌需要保存完整的三張牌組合
    if action.action == ActionType.CHI:
        if len(action.tiles) != 3 or action.tile not in action.tiles:
            raise ValueError("invalid chi sequence")

        # 移除別人打出的牌，留下自己需要提供的兩張
        used_tiles = list(action.tiles)
        used_tiles.remove(action.tile)

    # 碰牌需要自己提供兩張相同的牌
    elif action.action == ActionType.PONG:
        used_tiles = [action.tile, action.tile]

    else:
        raise ValueError("only CHI and PONG are supported")

    # 在副本上操作，避免修改原始手牌
    cards = list(hand)

    for tile in used_tiles:
        if tile not in cards:
            raise ValueError(f"meld tile not in hand: {tile}")

        cards.remove(tile)

    return tuple(cards)


# 評估吃碰之後，再打出一張牌的最佳結果
# 評估吃碰後的最佳棄牌，保留完整有效進張明細
def evaluate_meld_details(
    hand: tuple[Tile, ...],
    action: LegalAction,
    meld_count: int,
) -> tuple[int, tuple[Tile, ...], Tile]:
    remaining_hand = simulate_meld(hand, action)

    # 吃碰後新增一組副露
    calculator = MeldShantenCalculator(meld_count + 1)

    if not remaining_hand:
        raise ValueError("no tile to discard after meld")

    # 保留原本的向聽、進張種類數及牌 ID 排序
    tile, shanten, draws = min(
        iter_best_discard_evaluations(
            remaining_hand,
            sorted(set(remaining_hand)),
            calculator,
        ),
        key=lambda item: (
            item[1],
            -len(item[2]),
            item[0],
        ),
    )

    # 保留完整進張明細，讓候選評分直接重用
    return shanten, draws, tile


# 保留原本介面，既有吃碰與槓牌策略不需要更改
def evaluate_meld(
    hand: tuple[Tile, ...],
    action: LegalAction,
    meld_count: int,
) -> tuple[int, int, Tile]:
    shanten, draws, tile = evaluate_meld_details(
        hand,
        action,
        meld_count,
    )

    return shanten, len(draws), tile


# 吃碰策略，根據向聽數判斷是否值得副露
class MeldEfficiencyPolicy:
    strategy_version = "meld_efficiency_v0"

    def decide(
        self,
        observation: Observation,
        legal_actions: LegalActions,
    ) -> Decision:
        if not legal_actions:
            raise ValueError("legal_actions cannot be empty")

        # 如果可以胡牌，優先選擇 WIN
        for action in legal_actions:
            if action.action == ActionType.WIN:
                return Decision(
                    action=action,
                    score=1.0,
                    reason="win is available",
                )

        # 取得自己的副露組數，建立對應的向聽計算器
        meld_count = len(observation.melds[observation.seat])
        calculator = MeldShantenCalculator(meld_count)

        # 從合法動作中找出 PASS
        pass_action = next(
            (
                action
                for action in legal_actions
                if action.action == ActionType.PASS
            ),
            None,
        )

        # 只取出 CHI 與 PONG 作為副露評估候選
        meld_actions = [
            action
            for action in legal_actions
            if action.action in (ActionType.CHI, ActionType.PONG)
        ]

        # 有 PASS 且可以吃碰時，開始比較副露結果
        if pass_action is not None and meld_actions:
            # 計算目前不吃碰時的向聽數
            current_shanten = calculator.calculate(observation.hand)

            best = None
            best_action = None

            # 逐一評估 Rules 提供的合法吃碰動作
            for action in meld_actions:
                shanten, effective_count, discard_tile = evaluate_meld(
                    observation.hand,
                    action,
                    meld_count,
                )

                candidate = (
                    shanten,
                    -effective_count,
                    discard_tile,
                )

                # 保留結果較好的動作，平手時沿用原本順序
                if best is None or candidate < best:
                    best = candidate
                    best_action = action

            # 只有吃碰後確實降低向聽數，才選擇副露
            if best is not None and best[0] < current_shanten:
                return Decision(
                    action=best_action,
                    score=float(-best[0]),
                    reason=(
                        f"meld shanten = {best[0]}, "
                        f"effective_draws = {-best[1]}, "
                        f"next_discard = {best[2]}"
                    ),
                )

            # 吃碰無法改善向聽數時，選擇 PASS
            return Decision(
                action=pass_action,
                score=float(-current_shanten),
                reason="pass: meld does not reduce shanten",
            )

        # 沒有需要比較的吃碰動作時，沿用基本策略
        return BaselinePolicy(calculator).decide(
            observation,
            legal_actions,
        )