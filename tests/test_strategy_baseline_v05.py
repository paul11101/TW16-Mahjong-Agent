from dataclasses import replace

import pytest

from src.common.schemas import ActionType
from src.strategy.baseline import BaselinePolicy, BaselineV05Policy
from src.strategy.interfaces import LegalAction, Observation


# 建立假的向聽計算器
# 打出牌 0 後，有效進張為牌 2
# 打出牌 1 後，有效進張為牌 3
class FakeEqualShantenCalculator:
    def calculate(self, hand: tuple[int, ...]) -> int:
        if len(hand) == 1:
            return 1

        if hand in ((1, 2), (0, 3)):
            return 0

        return 1


# 建立不同向聽數的測試計算器
class FakeLowerShantenCalculator:
    def calculate(self, hand: tuple[int, ...]) -> int:
        if hand == (1,):
            return 0

        if hand == (0,):
            return 1

        return 1


# 建立有效進張種類數不同的測試計算器
class FakeEffectiveTypesCalculator:
    def calculate(self, hand: tuple[int, ...]) -> int:
        if len(hand) == 1:
            return 1

        if hand in ((1, 2), (1, 3), (0, 4)):
            return 0

        return 1


# 建立固定的測試牌局
def make_observation():
    return Observation(
        hand = (0, 1),
        discards = ((), (), (), ()),
        melds = ((), (), (), ()),
        flowers = ((), (), (), ()),
        current_player = 0,
        seat = 0,
        remaining_tiles = 80,
    )


# 建立兩個合法棄牌動作
def make_legal_actions():
    return [
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


# 測試新版是否會優先選擇未見牌數較多的有效進張
def test_v05_prefers_more_unseen_tiles():
    observation = replace(
        make_observation(),
        discards = ((2, 2, 2), (3,), (), ()),
    )

    legal_actions = make_legal_actions()
    calculator = FakeEqualShantenCalculator()

    # 建立舊版及新版 Baseline
    old_policy = BaselinePolicy(calculator)
    new_policy = BaselineV05Policy(calculator)

    old_decision = old_policy.decide(observation, legal_actions)
    new_decision = new_policy.decide(observation, legal_actions)

    # 舊版只比較進張種類數，兩種出牌相同時選第一個
    assert old_decision.action.id == "discard_0"

    # 牌 2 最多剩一張，牌 3 最多剩三張
    # 新版應打出牌 1，保留等待牌 3 的機會
    assert new_decision.action.id == "discard_1"
    assert "unseen_upper_bound = 3" in new_decision.reason


# 測試公開副露是否會影響新版的出牌選擇
def test_v05_uses_public_melds():
    observation = replace(
        make_observation(),
        melds = (((3, 3, 3),), (), (), ()),
    )

    policy = BaselineV05Policy(FakeEqualShantenCalculator())
    decision = policy.decide(observation, make_legal_actions())

    # 牌 3 已公開碰出三張，最多剩一張未見
    # 牌 2 未公開出現，最多還有四張未見
    assert decision.action.id == "discard_0"
    assert "unseen_upper_bound = 4" in decision.reason


# 測試新版仍然以最低向聽數為最高優先順序
def test_v05_prefers_lower_shanten():
    policy = BaselineV05Policy(FakeLowerShantenCalculator())

    decision = policy.decide(
        make_observation(),
        make_legal_actions(),
    )

    # 打出牌 0 後向聽數為 0，優於打出牌 1
    assert decision.action.id == "discard_0"
    assert "shanten = 0" in decision.reason


# 測試未見張數相同時，優先比較有效進張種類數
def test_v05_uses_effective_types_as_tiebreaker():
    observation = replace(
        make_observation(),
        discards = ((2, 2, 2), (3, 3, 3), (4, 4), ()),
    )

    # 故意把 discard_1 放在第一個
    legal_actions = list(reversed(make_legal_actions()))

    policy = BaselineV05Policy(FakeEffectiveTypesCalculator())
    decision = policy.decide(observation, legal_actions)

    # 打出 0：有效進張為 2、3，各剩一張，合計兩張
    # 打出 1：有效進張為 4，剩兩張
    # 未見張數總和相同，因此應優先選擇兩種進張
    assert decision.action.id == "discard_0"
    assert "effective_draws = 2" in decision.reason


# 測試已經全部出現的牌不應計入可用進張
def test_v05_ignores_exhausted_effective_tiles():
    observation = replace(
        make_observation(),
        discards = ((2, 2, 2, 2), (3, 3, 3, 3), (), ()),
    )

    policy = BaselineV05Policy(FakeEqualShantenCalculator())
    decision = policy.decide(observation, make_legal_actions())

    # 牌 2 與牌 3 都已公開四張，沒有剩餘未見牌
    assert decision.action.id == "discard_0"
    assert "effective_draws = 0" in decision.reason
    assert "unseen_upper_bound = 0" in decision.reason


# 測試評估結果完全相同時，保留原本合法動作順序
def test_v05_keeps_legal_action_order_on_tie():
    legal_actions = list(reversed(make_legal_actions()))

    policy = BaselineV05Policy(FakeEqualShantenCalculator())
    decision = policy.decide(make_observation(), legal_actions)

    # 兩種出牌的向聽與有效進張相同
    # 因此應選擇排列在前面的 discard_1
    assert decision.action.id == "discard_1"


# 測試能夠胡牌時，WIN 永遠具有最高優先順序
def test_v05_always_prefers_win():
    legal_actions = make_legal_actions() + [
        LegalAction(id = "win", action = ActionType.WIN),
    ]

    policy = BaselineV05Policy(FakeEqualShantenCalculator())
    decision = policy.decide(make_observation(), legal_actions)

    assert decision.action.action == ActionType.WIN


# 測試沒有提供向聽計算器時，仍能使用原本 Baseline
def test_v05_without_calculator_uses_old_baseline():
    policy = BaselineV05Policy()

    decision = policy.decide(
        make_observation(),
        make_legal_actions(),
    )

    # 沒有計算器時，直接選擇第一個合法棄牌
    assert decision.action.id == "discard_0"
    assert decision.reason == "baseline discard"


# 測試沒有合法棄牌，但可以 PASS 的情況
def test_v05_supports_pass():
    legal_actions = [
        LegalAction(id = "pass", action = ActionType.PASS),
    ]

    policy = BaselineV05Policy(FakeEqualShantenCalculator())
    decision = policy.decide(make_observation(), legal_actions)

    assert decision.action.action == ActionType.PASS


# 測試沒有任何合法動作時，應拋出 ValueError
def test_v05_rejects_empty_legal_actions():
    policy = BaselineV05Policy(FakeEqualShantenCalculator())

    with pytest.raises(ValueError, match = "legal_actions cannot be empty"):
        policy.decide(make_observation(), [])


# 測試剩餘牌數未知時，出牌決策仍然一致
def test_v05_supports_unknown_remaining_tiles():
    observation = make_observation()
    unknown = replace(observation, remaining_tiles = None)

    policy = BaselineV05Policy(FakeEqualShantenCalculator())
    legal_actions = make_legal_actions()

    first_decision = policy.decide(observation, legal_actions)
    second_decision = policy.decide(unknown, legal_actions)

    # 目前 v0.5 不使用剩餘牌數直接推算有效進張
    assert first_decision == second_decision


# 測試公開已知的同種牌超過四張時，應拒絕不合理資訊
def test_v05_rejects_invalid_visible_counts():
    observation = replace(
        make_observation(),
        discards = ((2, 2, 2), (), (), ()),
        melds = (((2, 2, 2),), (), (), ()),
    )

    policy = BaselineV05Policy(FakeEqualShantenCalculator())

    # 牌 2 在河牌及副露中共出現六張，超過四張
    with pytest.raises(ValueError, match = "exceeds four copies"):
        policy.decide(observation, make_legal_actions())


# 測試策略決策不會修改原本的 Observation
def test_v05_does_not_mutate_observation():
    observation = make_observation()
    before = replace(observation)

    policy = BaselineV05Policy(FakeEqualShantenCalculator())
    policy.decide(observation, make_legal_actions())

    assert observation == before