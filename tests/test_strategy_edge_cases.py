import pytest

from src.common.schemas import ActionType
from src.strategy.baseline import BaselinePolicy
from src.strategy.interfaces import LegalAction, Observation
from src.strategy.shanten import Taiwan16ShantenCalculator
from src.strategy.tile_efficiency import effective_draws


# 建立測試用的 Strategy Observation
def make_observation(hand: tuple[int, ...]) -> Observation:
    return Observation(
        # Agent 自己目前的手牌
        hand = hand,
        # 四位玩家目前都沒有棄牌
        discards = ((), (), (), ()),
        # 四位玩家目前都沒有副露
        melds = ((), (), (), ()),
        # 四位玩家目前都沒有花牌
        flowers = ((), (), (), ()),
        # 目前輪到玩家 0
        current_player = 0,
        # Agent 自己的座位為玩家 0
        seat = 0,
        # 測試用的假設剩餘牌數
        remaining_tiles = 80,
    )


# 測試向聽計算器是否會拒絕超出合法範圍的牌 ID
def test_shanten_rejects_invalid_tile():
    # 建立台灣 16 張向聽計算器
    calculator = Taiwan16ShantenCalculator()

    # 牌 ID 42 超出合法範圍 0~41，因此應該產生 ValueError
    with pytest.raises(ValueError):
        calculator.calculate((0, 1, 42,))


# 測試同一種普通牌超過四張時是否會被拒絕
def test_shanten_rejects_more_than_four_same_tiles():
    # 建立台灣 16 張向聽計算器
    calculator = Taiwan16ShantenCalculator()

    # 同一種牌最多只能有四張，第五張屬於非法牌型
    with pytest.raises(ValueError):
        calculator.calculate((0, 0, 0, 0, 0,))


# 測試花牌是否不會影響一般牌型的向聽數
def test_flower_does_not_affect_shanten():
    # 建立台灣 16 張向聽計算器
    calculator = Taiwan16ShantenCalculator()

    # 原始手牌
    hand = (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 18, 19, 20, 27)

    # 在原始手牌中加入一張花牌 34
    hand_with_flower = hand + (34,)

    # 花牌不參與一般牌型組合，因此加入花牌前後向聽數應該相同
    assert calculator.calculate(hand) == calculator.calculate(hand_with_flower)


# 測試已經持有四張相同牌時，不會把第五張相同牌算成有效進張
def test_effective_draws_does_not_include_fifth_copy():
    # 建立假的向聽計算器，只用來測試 effective_draws 的四張限制
    class FakeCalculator:
        # 五張牌時假設向聽數下降為 0，其他情況維持 1
        def calculate(self, hand: tuple[int, ...]) -> int:
            if len(hand) == 5:
                return 0
            return 1

    # 建立假的向聽計算器
    calculator = FakeCalculator()

    # 手牌已經持有四張牌 ID 0
    hand = (0, 0, 0, 0,)

    # 計算目前所有有效進張
    draws = effective_draws(hand, calculator)

    # 因為牌 ID 0 已經有四張，所以不能再把第五張 0 當成有效進張
    assert 0 not in draws


# 測試 Baseline 是否只會從 Rules 提供的合法棄牌中選擇
def test_baseline_only_selects_legal_discard():
    # 建立真正的台灣 16 張向聽計算器
    calculator = Taiwan16ShantenCalculator()

    # 建立固定測試手牌
    hand = (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 18, 19, 20, 27, 33,)

    # 將手牌建立成 Strategy Observation
    observation = make_observation(hand)

    # Rules 假設目前只允許打出牌 27 或牌 33
    legal_actions = [
        LegalAction(
            id = "discard_27",
            action = ActionType.DISCARD,
            tile = 27,
        ),
        LegalAction(
            id = "discard_33",
            action = ActionType.DISCARD,
            tile = 33,
        ),
    ]

    # 使用真正的牌效率 Baseline 做決策
    decision = BaselinePolicy(calculator).decide(observation, legal_actions,)

    # 最後選擇的動作一定必須存在於 LegalActions 中
    assert decision.action in legal_actions


# 測試相同輸入下 Baseline 是否每次都會得到相同結果
def test_baseline_result_is_deterministic():
    # 建立真正的台灣 16 張向聽計算器
    calculator = Taiwan16ShantenCalculator()

    # 建立固定測試手牌
    hand = (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 18, 19, 20, 27, 33,)

    # 將手牌建立成 Strategy Observation
    observation = make_observation(hand)

    # 根據目前手牌建立所有合法 DISCARD 動作
    # 相同牌只需要建立一個棄牌動作
    legal_actions = [
        LegalAction(
            id = f"discard_{tile}",
            action = ActionType.DISCARD,
            tile = tile,
        )
        for tile in sorted(set(hand))
    ]

    # 建立牌效率 Baseline
    policy = BaselinePolicy(calculator)

    # 先取得第一次的決策結果作為基準
    first = policy.decide(observation, legal_actions,)

    # 使用完全相同的輸入重複決策 20 次
    for _ in range(20):
        decision = policy.decide(observation, legal_actions,)

        # Baseline 不包含隨機選擇，因此每次結果都應該與第一次相同
        assert decision.action == first.action