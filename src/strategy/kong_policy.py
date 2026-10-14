from src.common.schemas import ActionType
from .interfaces import Decision, LegalAction, LegalActions, Observation, Tile
from .meld_policy import MeldEfficiencyPolicy, MeldShantenCalculator, evaluate_meld
from .tile_efficiency import effective_draws, evaluate_discard


# 根據槓牌種類，模擬槓牌後、尚未補牌的暗牌
# 明槓與暗槓會增加一組副露，加槓只是原本碰牌升級，不增加面子數
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
        # 加槓必須先有一組相同牌的碰牌，不能當作新的面子
        if (tile, tile, tile) not in own_melds:
            raise ValueError("added kong requires an existing pong")

        used_count = 1
        meld_increase = 0

    # 確認手牌數量符合對應槓牌種類
    if cards.count(tile) != used_count:
        raise ValueError("invalid number of tiles for kong")

    # 移除實際用於槓牌的暗牌
    for _ in range(used_count):
        cards.remove(tile)

    return tuple(cards), meld_increase


# D4 槓牌策略：比較槓後的向聽與有效補牌，決定槓牌或維持 D3 決策
class KongEfficiencyPolicy:
    strategy_version = "kong_efficiency_v0"

    def decide(self, observation: Observation, legal_actions: LegalActions) -> Decision:
        if not legal_actions:
            raise ValueError("legal_actions cannot be empty")

        # 胡牌優先於吃、碰、槓、過
        for action in legal_actions:
            if action.action == ActionType.WIN:
                return Decision(action = action, score = 1.0, reason = "win is available")

        # 非槓牌動作沿用 D3 的選擇，避免破壞原本吃碰及出牌策略
        other_actions = [action for action in legal_actions if action.action != ActionType.KONG]
        kong_actions = [action for action in legal_actions if action.action == ActionType.KONG]

        if not kong_actions:
            return MeldEfficiencyPolicy().decide(observation, legal_actions)

        meld_count = len(observation.melds[observation.seat])
        own_melds = observation.melds[observation.seat]
        calculator = MeldShantenCalculator(meld_count)
        base_decision = MeldEfficiencyPolicy().decide(observation, other_actions) if other_actions else None

        # PASS 比較的是保留手牌的向聽與進張；自己回合則比較正常棄牌
        base_shanten = 99
        base_effective_count = -1

        if base_decision is not None:
            action = base_decision.action

            if action.action == ActionType.PASS:
                base_shanten = calculator.calculate(observation.hand)
                base_effective_count = len(effective_draws(observation.hand, calculator, current_shanten = base_shanten,))

            elif action.action in (ActionType.CHI, ActionType.PONG):
                base_shanten, base_effective_count, _ = evaluate_meld(observation.hand, action, meld_count)

            elif action.action == ActionType.DISCARD:
                base_shanten, draws = evaluate_discard(observation.hand, action.tile, calculator,)
                base_effective_count = len(draws)

        best_action = None
        best_quality = None

        # 牌牆剩餘不足時不主動槓牌，保留 Rules 預設的海底保留 16 張
        if observation.remaining_tiles is None or observation.remaining_tiles > 16:
            for action in kong_actions:
                # 介面缺少 kong_type 時不猜測種類，避免把加槓錯算成明槓
                if action.kong_type not in ("ming", "an", "jia"):
                    continue

                # 模擬槓牌，取得槓後暗牌與新增面子數
                after_kong, meld_increase = simulate_kong(observation.hand, action, own_melds)
                next_calculator = MeldShantenCalculator(meld_count + meld_increase)

                # 槓牌後會補一張未知牌，這裡只估計補牌前向聽與有效進張
                shanten = next_calculator.calculate(after_kong)
                draws = effective_draws(after_kong, next_calculator, current_shanten = shanten,)

                # 槓牌使用的四張牌都已現身，不能把相同牌當成可能補到的進張
                effective_count = len([tile for tile in draws if tile != action.tile])
                quality = (shanten, -effective_count)

                # 保留目前牌效率最好的槓牌候選
                if best_quality is None or quality < best_quality:
                    best_quality = quality
                    best_action = action

        if best_action is not None:
            kong_shanten = best_quality[0]
            kong_effective_count = -best_quality[1]

            # 向聽改善可以槓；向聽相同時，必須保留足夠有效補牌才槓
            # 若尚有其他行動，不能因槓牌而降低原本的牌效率
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

        # 評估不值得槓時，選擇原本 D3 的 CHI／PONG／PASS／DISCARD
        if base_decision is not None:
            return base_decision

        # 只剩槓牌一種合法動作時，不能選擇不存在的 PASS
        return Decision(action = legal_actions[0], score = 0.0, reason = "only legal kong action")