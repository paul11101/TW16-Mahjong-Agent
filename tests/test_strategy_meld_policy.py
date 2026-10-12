
import pytest

from src.common.schemas import ActionType
from src.rules.legal_actions import LegalActionGenerator
from src.strategy.adapters import actions_to_legal_actions
from src.strategy.interfaces import LegalAction, Observation
from src.strategy.meld_policy import MeldEfficiencyPolicy, MeldShantenCalculator, simulate_meld

# 固定測試手牌，分別用於吃、碰以及過牌判斷
CHI_HAND = (0, 1, 2, 9, 10, 11, 18, 19, 20, 27, 27, 3, 4, 6, 7, 33)
PONG_HAND = (0, 1, 2, 9, 10 ,11, 18, 19, 20, 27, 27, 33, 33, 6, 7, 24)
PASS_HAND = (0, 1, 2, 3 ,4 ,5, 9, 10, 11, 18, 19, 20, 27, 27, 6, 7)

# 建立測試用的 Observation，模擬目前玩家看得到的牌局資料
def make_observation(hand, melds = ()):
    return Observation(
        hand = hand,
        discards = ((), (), (), ()),
        melds = (tuple(melds), (), (), ()),
        flowers = ((), (), (), ()),
        current_player = 3,
        seat = 0,
        remaining_tiles = 80,
    )


# 使用真正的 Rules 產生合法反應，再轉成 Strategy 使用的格式
def make_legal_actions(hand, target_tile, is_previous_player):
    rules_actions = LegalActionGenerator().get_response_actions(
        hand = list(hand),
        target_tile = target_tile,
        is_previous_player = is_previous_player,
    )

    return actions_to_legal_actions(rules_actions)


# 測試吃牌能改善向聽數時，策略是否選擇 CHI
def test_chi_reduces_shanten():
    # 建立合法吃牌動作與目前手牌資訊
    legal_actions = make_legal_actions(CHI_HAND, 5, True)
    observation = make_observation(CHI_HAND)

    # 執行吃碰策略
    decision = MeldEfficiencyPolicy().decide(observation, legal_actions)

    # 確認選擇 CHI，且動作來自 Rules 提供的合法集合
    assert decision.action.action == ActionType.CHI
    assert decision.action in legal_actions

    # 決策原因應記錄吃牌後的向聽數
    assert "shanten = 0" in decision.reason


# 測試碰牌能改善向聽數時，策略是否選擇 PONG
def test_pong_reduces_shanten():
    # 建立可以碰牌的牌型
    legal_actions = make_legal_actions(PONG_HAND, 33, False)
    observation = make_observation(PONG_HAND)

    # 執行策略並取得決策
    decision = MeldEfficiencyPolicy().decide(observation, legal_actions)

    # 確認選擇 PONG，且屬於合法動作
    assert decision.action.action == ActionType.PONG
    assert decision.action in legal_actions

    # 確認碰牌後的向聽數為 0
    assert "shanten = 0" in decision.reason


# 測試吃碰無法改善牌型時，策略是否選擇 PASS
def test_pass_when_meld_does_not_improve():
    # 建立有碰牌機會的合法動作
    legal_actions = make_legal_actions(PASS_HAND, 27, False)

    # 執行策略評估
    decision = MeldEfficiencyPolicy().decide(make_observation(PASS_HAND), legal_actions)

    # 確認 Rules 允許碰牌，但策略決定放棄
    assert ActionType.PONG in {a.action for a in legal_actions}
    assert decision.action.action == ActionType.PASS


# 測試 WIN 是否優先於 CHI、PONG、PASS
def test_win_takes_priority():
    # 建立同時包含碰牌、胡牌與過牌的合法動作
    legal_actions = [
        LegalAction(id = "pong_27", action = ActionType.PONG, tile = 27, tiles = (27, 27, 27)),
        LegalAction(id = "win_27", action = ActionType.WIN, tile = 27),
        LegalAction(id = "pass", action = ActionType.PASS),
    ]

    # 執行策略並確認胡牌優先
    decision = MeldEfficiencyPolicy().decide(make_observation(PASS_HAND), legal_actions)

    assert decision.action.action == ActionType.WIN


# 測試已經完成一組副露時的向聽計算
def test_open_meld_shanten():
    # 暗牌剩下四組面子及一對眼睛
    hand = (0, 1, 2, 3, 4, 5, 9, 10, 11, 18, 19, 20, 27, 27)

    # 因為已有一組副露，暗牌完成後的向聽數應為 -1
    assert MeldShantenCalculator(meld_count = 1).calculate(hand) == -1


# 測試模擬碰牌時，只移除自己手上的兩張
def test_simulate_pong_consumes_two_tiles():
    # 假設別人打出 33，而自己手上有兩張 33
    action = LegalAction(id = "pong_33", action = ActionType.PONG, tile = 33, tiles = (33, 33, 33))

    # 模擬碰牌後剩下的暗牌
    remaining = simulate_meld(PONG_HAND, action)

    # 確認兩張 33 已被移除，其他手牌數量正確
    assert remaining.count(33) == 0
    assert len(remaining) == len(PONG_HAND) - 2
    assert PONG_HAND.count(33) == 2


# 測試手牌不存在指定牌時，是否正確拒絕非法副露
def test_rejects_invalid_meld():
    # 嘗試碰手上不存在的 32
    action = LegalAction(id = "pong_32", action = ActionType.PONG, tile = 32, tiles = (32, 32, 32))

    # 預期 simulate_meld 會拋出 ValueError
    with pytest.raises(ValueError):
        simulate_meld(CHI_HAND, action)


# 測試已經副露之後，策略仍能選擇合法棄牌
def test_discard_after_exposed_meld():
    # 目前暗牌與已經完成的一組副露
    hand = (0, 1, 2, 3, 4, 5, 9, 10, 11, 18, 19, 20, 27, 27)
    observation = make_observation(hand, melds = ((30, 30, 30),))

    # 為目前手牌建立所有合法棄牌動作
    legal_actions = [
        LegalAction(id = f"discard_{tile}", action = ActionType.DISCARD, tile = tile)
        for tile in sorted(set(hand))
    ]

    # 執行策略並確認最後選擇的是合法棄牌
    decision = MeldEfficiencyPolicy().decide(observation, legal_actions)

    assert decision.action in legal_actions
    assert decision.action.action == ActionType.DISCARD


# 測試 D3 尚未實作槓牌評估時，是否先選擇 PASS
def test_kong_still_uses_pass():
    # 建立可以槓牌與過牌的兩種合法動作
    legal_actions = [
        LegalAction(id = "kong_33", action = ActionType.KONG, tile = 33, tiles = (33, 33, 33, 33)),
        LegalAction(id = "pass", action = ActionType.PASS),
    ]

    # D4 才會處理 KONG，D3 暫時沿用 PASS
    decision = MeldEfficiencyPolicy().decide(make_observation(PONG_HAND), legal_actions)

    assert decision.action.action == ActionType.PASS
