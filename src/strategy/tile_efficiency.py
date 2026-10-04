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