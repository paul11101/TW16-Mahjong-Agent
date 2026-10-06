from src.common.schemas import ActionType
from src.strategy.baseline import BaselinePolicy
from src.strategy.interfaces import Observation, LegalAction


# 建立假的向聽計算器
# 用不同手牌回傳不同向聽數，測試 Baseline 是否優先選擇較低向聽
class FakeShantenCalculator:
    # 根據剩餘手牌決定假的向聽數
    def calculate(self, hand: tuple[int, ...]) -> int:
        # 剩下牌 0 時設定為一向聽
        if hand == (0,):
            return 1

        # 剩下牌 1 時設定為二向聽
        if hand == (1,):
            return 2

        # 其他情況固定回傳 2
        return 2


# 建立兩個 Baseline 測試共用的 Observation
def make_observation() -> Observation:
    return Observation(
        # 測試手牌只有牌 0 與牌 1
        hand = (0, 1,),

        # 四位玩家目前都沒有棄牌
        discards = ((), (), (), (),),

        # 四位玩家目前都沒有副露
        melds = ((), (), (), (),),

        # 四位玩家目前都沒有花牌
        flowers = ((), (), (), (),),

        # 目前輪到玩家 0
        current_player = 0,

        # Agent 自己也是玩家 0
        seat = 0,

        # 假設牌牆剩餘 80 張
        remaining_tiles = 80,
    )


# 測試 Baseline 是否優先選擇出牌後向聽數較低的動作
def test_baseline_prefers_lower_shanten():
    # 建立測試 Observation
    observation = make_observation()

    # 提供兩個合法棄牌動作
    legal_actions = [
        LegalAction(
            id = "discard_0",
            action = ActionType.DISCARD,
            tile = 0,
        ),
        LegalAction(
            id = "discard_1",
            action = ActionType.DISCARD,
            tile = 1,
        ),
    ]

    # 建立假的向聽計算器
    calculator = FakeShantenCalculator()

    # 將向聽計算器傳入 Baseline
    policy = BaselinePolicy(calculator)

    # 執行策略決策
    decision = policy.decide(observation, legal_actions,)

    # 打掉牌 1 後剩下 (0,)
    # FakeShantenCalculator 會回傳 1，因此應該選 discard_1
    assert decision.action.id == "discard_1"

    # 決策原因中應該記錄最後選擇的向聽數
    assert "shanten = 1" in decision.reason


# 建立假的有效進張測試計算器
# 兩種出牌後向聽數相同，但有效進張種類不同
class FakeEffectiveDrawCalculator:
    # 根據手牌內容回傳假的向聽數
    def calculate(self, hand: tuple[int, ...]) -> int:
        # 兩種候選出牌後都設定為一向聽
        if hand == (0,) or hand == (1,):
            return 1

        # 剩下牌 0 時，只有摸到牌 2 可以降低向聽
        if len(hand) == 2 and hand[0] == 0:
            if hand[1] == 2:
                return 0
            return 1

        # 剩下牌 1 時，摸到牌 2 或牌 3 都可以降低向聽
        if len(hand) == 2 and hand[0] == 1:
            if hand[1] in (2, 3):
                return 0
            return 1

        # 其他情況維持一向聽
        return 1


# 測試向聽數相同時，Baseline 是否選擇有效進張種類較多的出牌
def test_baseline_prefers_more_effective_draws():
    # 建立測試 Observation
    observation = make_observation()

    # 提供兩個合法棄牌動作
    legal_actions = [
        LegalAction(
            id = "discard_0",
            action = ActionType.DISCARD,
            tile = 0,
        ),
        LegalAction(
            id = "discard_1",
            action = ActionType.DISCARD,
            tile = 1,
        )
    ]

    # 建立假的有效進張計算器
    calculator = FakeEffectiveDrawCalculator()

    # 將計算器傳入 Baseline
    policy = BaselinePolicy(calculator)

    # 執行策略決策
    decision = policy.decide(observation, legal_actions,)

    # 打掉牌 0 後剩下 (1,)
    # 有效進張為牌 2、牌 3，共兩種
    # 打掉牌 1 後剩下 (0,)
    # 有效進張只有牌 2，共一種
    # 因此應該選擇 discard_0
    assert decision.action.id == "discard_0"

    # 決策原因應該記錄兩種有效進張
    assert "effective_draws = 2" in decision.reason