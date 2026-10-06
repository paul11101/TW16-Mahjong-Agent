import pytest

# 匯入要測試的牌效率相關函式
from src.strategy.tile_efficiency import (
    remove_discard,
    shanten_after_discard,
)


# 建立假的向聽計算器
# 目前不實作真正的向聽演算法，只固定回傳 2
# 用來測試 Strategy 是否能正常呼叫 calculate()
class FakeShantenCalculator:
    def calculate(self, hand: tuple[int, ...]) -> int:
        return 2


# 測試正常移除一張手牌
def test_remove_discard():
    # 手牌中有兩張牌 ID 3
    hand = (0, 1, 2, 3, 3,)

    # 模擬打出其中一張 3
    result = remove_discard(hand, 3,)

    # 應該只移除一張 3
    assert result == (0, 1, 2, 3,)


# 測試丟出不存在於手牌中的牌時是否會報錯
def test_remove_discard_rejects_missing_tile():
    hand = (0, 1, 2,)

    # 手牌沒有牌 ID 5，因此應該產生 ValueError
    with pytest.raises(ValueError):
        remove_discard(hand, 5,)


# 測試出牌後是否能正常呼叫向聽計算器
def test_shanten_after_discard():
    hand = (0, 1, 2, 3,)

    # 建立假的向聽計算器
    calculator = FakeShantenCalculator()

    # 模擬打出牌 ID 3，再計算剩餘手牌的向聽數
    result = shanten_after_discard(hand, 3, calculator,)

    # FakeShantenCalculator 固定回傳 2
    assert result == 2