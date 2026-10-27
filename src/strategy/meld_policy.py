from src.common.schemas import ActionType
from .baseline import BaselineV05Policy
from .interfaces import Decision, LegalAction, LegalActions, Observation, Tile
from .public_features import extract_public_features
from .shanten import Taiwan16ShantenCalculator
from .tile_efficiency import iter_best_discard_evaluations


# 副露後只計算剩餘需要完成的面子
class MeldShantenCalculator(Taiwan16ShantenCalculator):
    def __init__(self, meld_count: int):
        if not 0 <= meld_count <= 5:
            raise ValueError("meld_count must be between 0 and 5")
        self.MAX_MELDS = 5 - meld_count


# 模擬吃碰，只移除自己提供的牌
def simulate_meld(hand: tuple[Tile, ...], action: LegalAction) -> tuple[Tile, ...]:
    if action.tile is None or not 0 <= action.tile < 34:
        raise ValueError("invalid meld target")
    if action.action == ActionType.CHI:
        if len(action.tiles) != 3 or action.tile not in action.tiles:
            raise ValueError("invalid chi sequence")
        used = list(action.tiles)
        used.remove(action.tile)
    elif action.action == ActionType.PONG:
        used = [action.tile, action.tile]
    else:
        raise ValueError("only CHI and PONG are supported")

    cards = list(hand)
    for tile in used:
        if tile not in cards:
            raise ValueError(f"meld tile not in hand: {tile}")
        cards.remove(tile)
    return tuple(cards)


# 評估吃碰後的最佳棄牌，公開資訊只影響平手比較
def evaluate_meld_details(
    hand: tuple[Tile, ...], action: LegalAction, meld_count: int,
    *, unseen_upper_bounds: tuple[int, ...] | None = None,
) -> tuple[int, tuple[Tile, ...], Tile]:
    remaining = simulate_meld(hand, action)
    if not remaining:
        raise ValueError("no tile to discard after meld")
    calculator = MeldShantenCalculator(meld_count + 1)
    unseen = unseen_upper_bounds

    # 未提供公開資訊時，保留舊介面的比較結果
    def quality(item):
        tile, shanten, draws = item
        available = draws if unseen is None else tuple(t for t in draws if unseen[t] > 0)
        count = len(available)
        upper_bound = count if unseen is None else sum(unseen[t] for t in available)
        return shanten, -upper_bound, -count, tile

    tile, shanten, draws = min(
        iter_best_discard_evaluations(remaining, sorted(set(remaining)), calculator),
        key=quality,
    )
    return shanten, draws, tile


# 保留原本三個參數與回傳格式
def evaluate_meld(hand: tuple[Tile, ...], action: LegalAction, meld_count: int) -> tuple[int, int, Tile]:
    shanten, draws, tile = evaluate_meld_details(hand, action, meld_count)
    return shanten, len(draws), tile


# 吃碰必須降低向聽，並保留仍有未見張數的有效進張
class MeldEfficiencyPolicy:
    strategy_version = "meld_efficiency_v1"

    def decide(self, observation: Observation, legal_actions: LegalActions) -> Decision:
        if not legal_actions:
            raise ValueError("legal_actions cannot be empty")
        for action in legal_actions:
            if action.action == ActionType.WIN:
                return Decision(action, 1.0, "win is available")

        meld_count = len(observation.melds[observation.seat])
        calculator = MeldShantenCalculator(meld_count)
        pass_action = next((a for a in legal_actions if a.action == ActionType.PASS), None)
        meld_actions = [a for a in legal_actions if a.action in (ActionType.CHI, ActionType.PONG)]
        if pass_action is None or not meld_actions:
            return BaselineV05Policy(calculator).decide(observation, legal_actions)

        unseen = extract_public_features(observation).unseen_upper_bounds
        current_shanten = calculator.calculate(observation.hand)
        best = None
        best_action = None
        for action in meld_actions:
            shanten, draws, discard = evaluate_meld_details(
                observation.hand, action, meld_count, unseen_upper_bounds=unseen,
            )
            available = tuple(t for t in draws if unseen[t] > 0)
            # 不為了表面的向聽改善，副露成沒有有效進張的牌形
            if shanten >= current_shanten or not available:
                continue
            quality = (shanten, -sum(unseen[t] for t in available), -len(available), discard)
            if best is None or quality < best:
                best, best_action = quality, action

        if best is not None:
            shanten, negative_upper, negative_count, discard = best
            return Decision(
                best_action, float(-shanten),
                f"meld shanten = {shanten}, effective_draws = {-negative_count}, "
                f"unseen_upper_bound = {-negative_upper}, next_discard = {discard}",
            )
        return Decision(
            pass_action, float(-current_shanten),
            "pass: meld does not reduce shanten with available effective draws",
        )