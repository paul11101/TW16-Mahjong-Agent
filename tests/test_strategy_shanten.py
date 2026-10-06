from src.strategy.shanten import Taiwan16ShantenCalculator
from src.strategy.tile_efficiency import effective_draws


# 測試完整胡牌牌型的向聽數是否為 -1
def test_complete_hand_is_minus_one():
    # 建立真正的台灣 16 張向聽計算器
    calculator = Taiwan16ShantenCalculator()

    # 5 組完整面子加 1 對眼睛，共 17 張
    hand = (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 18, 19, 20, 27, 27,)

    # 已經完成胡牌，因此向聽數應為 -1
    assert calculator.calculate(hand) == -1


# 測試一向聽牌型是否正確回傳 1
def test_one_shanten_hand():
    # 建立真正的台灣 16 張向聽計算器
    calculator = Taiwan16ShantenCalculator()

    # 此牌型距離聽牌還需要改善一次
    hand = (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 18, 19, 27, 28,)

    # 預期為一向聽
    assert calculator.calculate(hand) == 1


# 測試真正的向聽計算器是否能找出有效進張
def test_effective_draws_with_real_calculator():
    # 建立真正的台灣 16 張向聽計算器
    calculator = Taiwan16ShantenCalculator()

    # 已經有五組面子，只缺一張 27 配成眼睛
    hand = (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 18, 19, 20, 27,)

    # 找出摸到後可以降低向聽數的牌
    draws = effective_draws(hand, calculator)

    # 只有再摸一張 27 能直接完成牌型
    assert draws == (27,)


# 測試聽牌狀態的向聽數是否為 0
def test_tenpai_hand_is_zero():
    # 建立真正的台灣 16 張向聽計算器
    calculator = Taiwan16ShantenCalculator()

    # 五組面子已完成，目前只有單張 27 等待配對
    hand = (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 18, 19, 20, 27,)

    # 已經聽牌，因此向聽數應為 0
    assert calculator.calculate(hand) == 0