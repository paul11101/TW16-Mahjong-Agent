from src.common.schemas import ActionType
from .interfaces import Decision, LegalAction, LegalActions, Observation, Tile
from .meld_policy import MeldEfficiencyPolicy, MeldShantenCalculator, evaluate_meld
from .tile_efficiency import effective_draws, evaluate_discard


# 模擬明槓、暗槓與加槓，回傳槓牌後的暗牌及新增面子數
def simulate_kong(hand: tuple[Tile, ...], action: LegalAction, own_melds: tuple[tuple[Tile, ...], ...]) -> tuple[tuple[Tile, ...], int]:
    if action.action != ActionType.KONG or action.tile is None or not 0 <= action.tile < 34:
        raise ValueError("invalid kong action")

    if action.kong_type not in ("ming", "an", "jia"):
        raise ValueError("unknown kong type")

    tile = action.tile
    cards = list(hand)

    if action.kong_type == "ming":
        used_count = 3
        meld_increase = 1

    elif action.kong_type == "an":
        used_count = 4
        meld_increase = 1

    else:
        if (tile, tile, tile) not in own_melds:
            raise ValueError("added kong requires an existing pong")

        used_count = 1
        meld_increase = 0

    if cards.count(tile) != used_count:
        raise ValueError("invalid number of tiles for kong")

    for _ in range(used_count):
        cards.remove(tile)

    return tuple(cards), meld_increase


# W4 D5 槓牌策略，完成 D4 決策邏輯的邊界修正
class KongEfficiencyPolicy:
    strategy_version = "kong_efficiency_v1"

    def decide(self, observation: Observation, legal_actions: LegalActions) -> Decision:
        if not legal_actions:
            raise ValueError("legal_actions cannot be empty")

        # 胡牌永遠優先
        for action in legal_actions:
            if action.action == ActionType.WIN:
                return Decision(action = action, score = 1.0, reason = "win is available")

        # 分離槓牌及其他合法動作
        other_actions = [action for action in legal_actions if action.action != ActionType.KONG]
        kong_actions = [action for action in legal_actions if action.action == ActionType.KONG]

        # 沒有槓牌時，維持 D3 原本決策
        if not kong_actions:
            return MeldEfficiencyPolicy().decide(observation, legal_actions)

        meld_count = len(observation.melds[observation.seat])
        own_melds = observation.melds[observation.seat]
        calculator = MeldShantenCalculator(meld_count)

        # 取得不槓牌時的基準策略
        base_decision = MeldEfficiencyPolicy().decide(observation, other_actions) if other_actions else None

        base_shanten = 99
        base_effective_count = -1

        if base_decision is not None:
            action = base_decision.action

            if action.action == ActionType.PASS:
                base_shanten = calculator.calculate(observation.hand)
                base_effective_count = len(effective_draws(
                    observation.hand,
                    calculator,
                    current_shanten = base_shanten,
                ))

            elif action.action in (ActionType.CHI, ActionType.PONG):
                base_shanten, base_effective_count, _ = evaluate_meld(
                    observation.hand,
                    action,
                    meld_count,
                )

            elif action.action == ActionType.DISCARD:
                base_shanten, draws = evaluate_discard(
                    observation.hand,
                    action.tile,
                    calculator,
                )
                base_effective_count = len(draws)

        best_action = None
        best_quality = None

        # D5 修正：牌牆數量未知或已達保留張數時，不主動槓牌
        if observation.remaining_tiles is not None and observation.remaining_tiles > 16:
            for action in kong_actions:
                # 槓牌種類不明時不自行猜測
                if action.kong_type not in ("ming", "an", "jia"):
                    continue

                # D5 修正：個別槓牌資料不正確時略過，不中斷其他合法決策
                try:
                    after_kong, meld_increase = simulate_kong(
                        observation.hand,
                        action,
                        own_melds,
                    )
                except ValueError:
                    continue

                next_calculator = MeldShantenCalculator(meld_count + meld_increase)

                # 槓牌後尚未取得補牌，因此只使用目前已知資訊評估
                shanten = next_calculator.calculate(after_kong)
                draws = effective_draws(
                    after_kong,
                    next_calculator,
                    current_shanten = shanten,
                )

                # 四張槓牌已經使用完畢，不能再把相同牌算成有效進張
                effective_count = len([tile for tile in draws if tile != action.tile])
                quality = (shanten, -effective_count)

                if best_quality is None or quality < best_quality:
                    best_quality = quality
                    best_action = action

        if best_action is not None:
            kong_shanten = best_quality[0]
            kong_effective_count = -best_quality[1]

            # 槓後向聽改善，或向聽相同且有效進張不減少，才考慮槓牌
            worthwhile = (
                base_decision is None
                or kong_shanten < base_shanten
                or (
                    kong_shanten == base_shanten
                    and kong_effective_count > 0
                    and kong_effective_count >= base_effective_count
                )
            )

            if worthwhile:
                return Decision(
                    action = best_action,
                    score = float(-kong_shanten),
                    reason = f"kong_type = {best_action.kong_type}, shanten = {kong_shanten}, effective_draws = {kong_effective_count}, replacement_draw = pending",
                )

        # 不值得槓時，使用 D3 選出的合法動作
        if base_decision is not None:
            return base_decision

        # D5 修正：沒有安全替代動作時明確報錯，不再強制選擇第一個 KONG
        raise ValueError("no safe legal action available")