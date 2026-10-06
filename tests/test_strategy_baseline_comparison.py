import random

from src.common.schemas import ActionType
from src.strategy.baseline import BaselinePolicy, RandomPolicy
from src.strategy.interfaces import Observation, LegalAction
from src.strategy.shanten import Taiwan16ShantenCalculator
from src.strategy.tile_efficiency import evaluate_discard


# 固定牌型測試資料
# 每組包含牌型名稱、17 張手牌與預期棄牌
FIXED_HANDS = [
    {
        # 測試 Baseline 是否會優先打掉孤立的字牌
        "name": "孤張字牌",
        "hand": (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 18, 19, 27, 27, 33,),
        "expected_discard": 33,
    },
    {
        # 測試 Baseline 是否會保留有價值的對子
        "name": "保留對子",
        "hand": (0, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 18, 19, 20, 33,),
        "expected_discard": 33,
    },
    {
        # 測試較複雜牌型下的向聽與有效進張判斷
        "name": "混合牌型一",
        "hand": (3, 3, 4, 5, 5, 5, 6, 7, 8, 18, 21, 22, 23, 26, 27, 27, 30,),
        "expected_discard": 30,
    },
    {
        # 第二組混合牌型，用來增加不同牌型的測試覆蓋
        "name": "混合牌型二",
        "hand": (0, 5, 9, 10, 10, 11, 11, 14, 15, 16, 16, 18, 24, 29, 29, 29, 31,),
        "expected_discard": 31,
    }
]


# 將固定手牌建立成 Strategy 使用的 Observation
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



# 根據目前手牌建立所有合法的 DISCARD 動作
def make_discard_actions(hand: tuple[int, ...]) -> list[LegalAction]:
    return [
        LegalAction(
            # 使用牌 ID 建立棄牌動作 ID
            id = f"discard_{tile}",

            # 此測試只建立 DISCARD 動作
            action = ActionType.DISCARD,

            # 指定要打出的牌
            tile = tile,
        )

        # 相同牌只需要建立一個棄牌動作
        for tile in sorted(set(hand))
    ]


# 評估某個 Decision 出牌後的結果
def evaluate_decision(hand, decision, calculator):
    # 計算該棄牌後的向聽數與有效進張
    shanten, draws = evaluate_discard(hand, decision.action.tile, calculator,)

    # 回傳向聽數與有效進張種類數
    return shanten, len(draws)


# 判斷第一個結果是否優於或等於第二個結果
def is_better_or_equal(first, second):
    # 拆出第一個結果的向聽數與有效進張種類數
    first_shanten, first_effective = first

    # 拆出第二個結果的向聽數與有效進張種類數
    second_shanten, second_effective = second

    # 向聽數較低代表牌型比較接近胡牌
    if first_shanten < second_shanten:
        return True

    # 向聽數相同時，比較有效進張種類數
    if first_shanten == second_shanten:
        return first_effective >= second_effective

    # 第一個結果向聽數較高，代表結果較差
    return False


# 測試 Baseline 是否能在固定牌型中選擇預期棄牌
def test_fixed_hands_baseline():
    # 建立真正的台灣 16 張向聽計算器
    calculator = Taiwan16ShantenCalculator()

    # 建立使用牌效率判斷的 Baseline
    policy = BaselinePolicy(calculator)

    # 逐一測試所有固定牌型
    for case in FIXED_HANDS:
        # 建立 Strategy Observation
        observation = make_observation(case["hand"])

        # 建立目前手牌所有合法棄牌
        legal_actions = make_discard_actions(case["hand"])

        # 讓 Baseline 選擇要打出的牌
        decision = policy.decide(observation, legal_actions,)

        # 確認 Baseline 選擇的牌符合預期
        assert decision.action.tile == case["expected_discard"], (
            f"{case['name']} 預期打 {case['expected_discard']}, "
            f"實際打 {decision.action.tile}"
        )


# 比較 RandomPolicy 與 BaselinePolicy 的出牌結果
def test_random_vs_baseline():
    # 建立真正的台灣 16 張向聽計算器
    calculator = Taiwan16ShantenCalculator()

    # 建立牌效率 Baseline
    baseline = BaselinePolicy(calculator)

    # 建立隨機策略作為比較對象
    random_policy = RandomPolicy()

    # 固定亂數種子，確保每次測試結果可以重現
    random.seed(42)

    # 記錄 Baseline 比 Random 好的次數
    baseline_better = 0

    # 記錄兩個策略結果相同的次數
    same_result = 0

    # 逐一測試所有固定牌型
    for case in FIXED_HANDS:
        # 建立 Strategy Observation
        observation = make_observation(case["hand"])

        # 建立所有合法棄牌
        legal_actions = make_discard_actions(case["hand"])

        # Baseline 對此牌型做一次決策
        baseline_decision = baseline.decide(observation, legal_actions,)

        # 評估 Baseline 出牌後的向聽與有效進張
        baseline_result = evaluate_decision(case["hand"], baseline_decision, calculator,)

        # 每個牌型讓 RandomPolicy 隨機選擇 100 次
        for _ in range(100):
            # RandomPolicy 隨機選擇一個合法棄牌
            random_decision = random_policy.decide(observation, legal_actions,)

            # 評估 Random 出牌後的結果
            random_result = evaluate_decision(case["hand"], random_decision, calculator,)

            # Baseline 的結果不應該比 Random 差
            assert is_better_or_equal(baseline_result, random_result,)

            # 如果兩者結果完全相同就記錄為相同
            if baseline_result == random_result:
                same_result += 1

            # 否則代表 Baseline 的結果較好
            else:
                baseline_better += 1

    # 至少要有一次 Baseline 的結果優於 Random
    assert baseline_better > 0

    # 顯示比較結果
    print()
    print(f"Baseline 較好: {baseline_better} 次")
    print(f"相同結果: {same_result} 次")