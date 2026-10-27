from src.common.schemas import ActionType
from .interfaces import Decision, LegalAction, LegalActions, Observation, Tile
from .meld_policy import MeldEfficiencyPolicy, MeldShantenCalculator, evaluate_meld_details
from .public_features import extract_public_features
from .tile_efficiency import effective_draws, evaluate_discard


# 模擬三種槓牌，回傳剩餘暗牌與新增面子數
def simulate_kong(
    hand: tuple[Tile, ...], action: LegalAction, own_melds: tuple[tuple[Tile, ...], ...],
) -> tuple[tuple[Tile, ...], int]:
    if action.action != ActionType.KONG or action.tile is None or not 0 <= action.tile < 34:
        raise ValueError("invalid kong action")
    if action.kong_type not in ("ming", "an", "jia"):
        raise ValueError("unknown kong type")

    tile = action.tile
    cards = list(hand)
    if action.kong_type == "ming":
        used_count, meld_increase = 3, 1
    elif action.kong_type == "an":
        used_count, meld_increase = 4, 1
    else:
        if (tile, tile, tile) not in own_melds:
            raise ValueError("added kong requires an existing pong")
        used_count, meld_increase = 1, 0

    if cards.count(tile) != used_count:
        raise ValueError("invalid number of tiles for kong")
    for _ in range(used_count):
        cards.remove(tile)
    return tuple(cards), meld_increase


# 槓牌只比較補牌前的已知牌形，未知補牌不計入收益
class KongEfficiencyPolicy:
    strategy_version = "kong_efficiency_v2"

    def decide(self, observation: Observation, legal_actions: LegalActions) -> Decision:
        if not legal_actions:
            raise ValueError("legal_actions cannot be empty")
        for action in legal_actions:
            if action.action == ActionType.WIN:
                return Decision(action, 1.0, "win is available")

        others = [a for a in legal_actions if a.action != ActionType.KONG]
        kongs = [a for a in legal_actions if a.action == ActionType.KONG]
        if not kongs:
            return MeldEfficiencyPolicy().decide(observation, legal_actions)

        own_melds = observation.melds[observation.seat]
        meld_count = len(own_melds)
        calculator = MeldShantenCalculator(meld_count)
        unseen = extract_public_features(observation).unseen_upper_bounds
        base = MeldEfficiencyPolicy().decide(observation, others) if others else None

        # 與棄牌相同：先向聽，再未見張數上限，最後進張種類數
        def quality(shanten, draws):
            available = tuple(t for t in draws if unseen[t] > 0)
            return shanten, -sum(unseen[t] for t in available), -len(available)

        base_quality = None
        if base is not None:
            action = base.action
            if action.action == ActionType.PASS:
                shanten = calculator.calculate(observation.hand)
                draws = effective_draws(observation.hand, calculator, current_shanten=shanten)
            elif action.action in (ActionType.CHI, ActionType.PONG):
                shanten, draws, _ = evaluate_meld_details(
                    observation.hand, action, meld_count, unseen_upper_bounds=unseen,
                )
            elif action.action == ActionType.DISCARD:
                shanten, draws = evaluate_discard(observation.hand, action.tile, calculator)
            else:
                raise ValueError("unsupported non-kong decision")
            base_quality = quality(shanten, draws)

        best_action = None
        best_quality = None
        # 保留原本的槓牌保守條件
        if observation.remaining_tiles is not None and observation.remaining_tiles > 16:
            for action in kongs:
                try:
                    remaining, increase = simulate_kong(observation.hand, action, own_melds)
                except ValueError:
                    continue
                next_calculator = MeldShantenCalculator(meld_count + increase)
                shanten = next_calculator.calculate(remaining)
                draws = effective_draws(remaining, next_calculator, current_shanten=shanten)
                draws = tuple(t for t in draws if t != action.tile)
                candidate = quality(shanten, draws)

                # 有其他選擇時，不主動槓成沒有有效進張的牌形
                if base is not None and candidate[2] == 0:
                    continue
                if best_quality is None or candidate < best_quality:
                    best_action, best_quality = action, candidate

        if best_action is not None and (base_quality is None or best_quality <= base_quality):
            shanten, negative_upper, negative_count = best_quality
            return Decision(
                best_action, float(-shanten),
                f"kong_type = {best_action.kong_type}, shanten = {shanten}, "
                f"effective_draws = {-negative_count}, unseen_upper_bound = {-negative_upper}, "
                "replacement_draw = pending",
            )
        if base is not None:
            return base
        raise ValueError("no safe legal action available")