from typing import Protocol
from .interfaces import Tile


# 定義向聽計算器需要遵守的介面
# 之後不管使用哪一種向聽演算法，只要有 calculate() 就可以使用
class ShantenCalculator(Protocol):
    # 傳入目前手牌，回傳向聽數
    def calculate(self, hand: tuple[Tile, ...]) -> int:
        ...


# 模擬從手牌中打出指定的一張牌
def remove_discard(hand: tuple[Tile, ...], tile: Tile,) -> tuple[Tile, ...]:
    # tuple 無法直接修改，因此先轉成 list
    cards = list(hand)

    # 如果要打出的牌不在手牌中，就代表輸入不合法
    if tile not in cards:
        raise ValueError(f"discard tile not in hand: {tile}")

    # 只移除其中一張相同的牌
    cards.remove(tile)

    # 再轉回 tuple，保持 Strategy 使用的固定格式
    return tuple(cards)


# 計算打出某張牌之後的向聽數
def shanten_after_discard(hand: tuple[Tile, ...], tile: Tile, calculator: ShantenCalculator,) -> int:
    # 先模擬打出指定的牌，取得出牌後的手牌
    remaining_hand = remove_discard(hand, tile,)

    # 將剩餘手牌交給向聽計算器並回傳結果
    return calculator.calculate(remaining_hand)


# 找出目前手牌的所有有效進張
def effective_draws(hand: tuple[Tile, ...], calculator: ShantenCalculator,) -> tuple[Tile, ...]:
    # 計算目前手牌的向聽數，之後用來判斷摸牌後是否有改善
    current_shanten = calculator.calculate(hand)

    # 儲存所有能降低向聽數的牌
    effective_tiles = []

    # 只檢查 34 種基本牌，花牌不參與一般牌型組合
    for tile in range(34):
        # 同一種牌最多只有四張，如果手上已經四張就不可能再摸到
        if hand.count(tile) >= 4:
            continue

        # 模擬摸到目前正在測試的牌
        next_hand = hand + (tile,)

        # 計算摸牌後的新向聽數
        next_shanten = calculator.calculate(next_hand)

        # 如果摸牌後向聽數下降，代表這張牌是有效進張
        if next_shanten < current_shanten:
            effective_tiles.append(tile)

    # 轉成 tuple 回傳所有有效進張
    return tuple(effective_tiles)


# 評估打出指定牌後的向聽數與有效進張
def evaluate_discard(hand: tuple[Tile, ...], tile: Tile, calculator: ShantenCalculator,) -> tuple[int, tuple[Tile, ...]]:
    # 模擬打出指定的一張牌
    remaining_hand = remove_discard(hand, tile,)

    # 計算打牌後的向聽數
    shanten = calculator.calculate(remaining_hand)

    # 計算打牌後有哪些有效進張
    draws = effective_draws(remaining_hand, calculator,)

    # 回傳向聽數與有效進張
    return shanten, draws