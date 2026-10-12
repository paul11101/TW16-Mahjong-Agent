
from src.common.schemas import ActionType
from .baseline import BaselinePolicy
from .interfaces import Decision, LegalAction, LegalActions, Observation, Tile
from .shanten import Taiwan16ShantenCalculator
from .tile_efficiency import evaluate_discard

# 副露後的向聽數計算器，繼承原本的台灣 16 張向聽演算法
class MeldShantenCalculator(Taiwan16ShantenCalculator):
    def __init__(self, meld_count: int):
        # 台麻最多需要五組面子，副露數量不可超出範圍
        if not 0 <= meld_count <= 5:
            raise ValueError("meld_count must be between 0 and 5")

        # 扣除已完成的副露面子，只計算剩餘需要完成的面子
        self.MAX_MELDS = 5 - meld_count


# 模擬吃牌或碰牌，計算副露後剩下的暗牌
def simulate_meld(hand: tuple[Tile, ...], action: LegalAction) -> tuple[Tile, ...]:
    # 確認目標牌屬於 0~33 的一般牌
    if action.tile is None or not 0 <= action.tile < 34:
        raise ValueError("invalid meld target")

    # 吃牌需要三張牌組成順子
    if action.action == ActionType.CHI:
        if len(action.tiles) != 3 or action.tile not in action.tiles:
            raise ValueError("invalid chi sequence")

        # 移除別人打出的目標牌，留下自己需要提供的兩張牌
        used_tiles = list(action.tiles)
        used_tiles.remove(action.tile)

    # 碰牌需要從自己的手牌取出兩張相同的牌
    elif action.action == ActionType.PONG:
        used_tiles = [action.tile, action.tile]

    # D3 暫時只支援 CHI 與 PONG
    else:
        raise ValueError("only CHI and PONG are supported")

    # tuple 無法直接修改，因此先轉成 list
    cards = list(hand)

    # 逐一移除吃碰時使用的手牌
    for tile in used_tiles:
        # 如果手上沒有指定牌，代表副露資料不合法
        if tile not in cards:
            raise ValueError(f"meld tile not in hand: {tile}")

        cards.remove(tile)

    # 回傳完成吃碰後剩餘的暗牌
    return tuple(cards)


# 評估吃碰之後，再打出一張牌的最佳結果
def evaluate_meld(hand:tuple[Tile, ...], action: LegalAction, meld_count: int) -> tuple[int, int, Tile]:
    # 模擬吃碰，取得副露後的暗牌
    remaining_hand = simulate_meld(hand, action)

    # 吃碰後新增一組副露，因此面子數加一
    calculator = MeldShantenCalculator(meld_count + 1)
    best = None

    # 模擬副露後每一種可能的棄牌
    for tile in sorted(set(remaining_hand)):
        # 計算棄牌後的向聽數與有效進張
        shanten, draws = evaluate_discard(remaining_hand, tile, calculator)

        # 優先比較向聽數，再比較有效進張種類數
        # 使用負數讓有效進張越多的候選結果越小
        candidate = (shanten, -len(draws), tile)

        # 如果目前結果比較好，就更新最佳候選
        if best is None or candidate < best:
            best = candidate

    # 副露後如果沒有可以打出的牌，就無法完成評估
    if best is None:
        raise ValueError("no tile to discard after meld")

    # 回傳最佳向聽數、有效進張種類數及預計棄牌
    return best[0], -best[1], best[2]


# W4 D3 吃碰策略，根據向聽數判斷是否值得副露
class MeldEfficiencyPolicy:
    strategy_version = "meld_efficiency_v0"

    # 根據 Observation 與 Rules 提供的合法動作進行決策
    def decide(self, observation: Observation, legal_actions: LegalActions) -> Decision:
        # 沒有合法動作時直接報錯
        if not legal_actions:
            raise ValueError("legal_actions cannot be empty")

        # 如果可以胡牌，就優先選擇 WIN
        for action in legal_actions:
            if action.action == ActionType.WIN:
                return Decision(action = action, score = 1.0, reason = "win is available")


        # 取得自己目前已經完成的副露數量
        meld_count = len(observation.melds[observation.seat])

        # 建立符合目前副露數量的向聽計算器
        calculator = MeldShantenCalculator(meld_count)

        # 從合法動作中找出 PASS
        pass_action = next((a for a in legal_actions if a.action == ActionType.PASS), None)

        # 只取出 CHI 與 PONG 作為副露評估候選
        meld_actions = [a for a in legal_actions if a.action in (ActionType.CHI, ActionType.PONG)]

        # 有 PASS 且可以吃碰時，開始進行副露比較
        if pass_action is not None and meld_actions:
            # 計算目前不吃碰時的向聽數
            current_shanten = calculator.calculate(observation.hand)
            best = None
            best_action = None

            # 逐一評估每個合法吃碰動作
            for action in meld_actions:
                # 計算吃碰後最佳棄牌的向聽數與有效進張
                shanten, effective_count, discard_tile = evaluate_meld(observation.hand, action, meld_count,)
                candidate = (shanten, -effective_count, discard_tile)

                # 保留目前評分最好的吃碰動作
                if best is None or candidate < best:
                    best = candidate
                    best_action = action


            # 只有吃碰後的向聽數確實降低，才執行副露
            if best is not None and best[0] < current_shanten:
                return Decision(
                    action = best_action,
                    score = float(-best[0]),
                    reason = f"meld shanten = {best[0]}, effective_draws = {-best[1]}, next_discard = {best[2]}",
                )

            # 吃碰無法改善向聽時，先選擇 PASS
            return Decision(action = pass_action, score = float(-current_shanten), reason = "pass: meld does not reduce shanten",)

        # 沒有需要評估的吃碰動作時，沿用 W3 Baseline 策略
        return BaselinePolicy(calculator).decide(observation, legal_actions)
