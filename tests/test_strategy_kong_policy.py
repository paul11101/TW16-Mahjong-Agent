import pytest

from src.common.schemas import ActionType
from src.rules.legal_actions import LegalActionGenerator
from src.rules.rule import Action
from src.strategy.adapters import action_to_legal_action, actions_to_legal_actions
from src.strategy.interfaces import LegalAction, Observation
from src.strategy.kong_policy import KongEfficiencyPolicy, simulate_kong
from src.strategy.meld_policy import MeldEfficiencyPolicy

MING_HAND = (0, 1, 2, 3, 4, 5, 9, 10, 11, 18, 19, 27, 27, 33, 33, 33)
AN_HAND = (0, 1, 2, 3, 4, 5, 9, 10, 11, 18, 19, 20, 27, 33, 33, 33, 33)
JIA_HAND = (0, 1, 2, 3, 4, 5, 9, 10, 11, 18, 19, 20, 27, 33)


# 建立反應與自己回合都能共用的 Observation
def make_observation(hand, melds = (), remaining_tiles = 80):
    return Observation(
        hand = hand,
        discards = ((), (), (), ()),
        melds = (tuple(melds), (), (), ()),
        flowers = ((), (), (), ()),
        current_player = 0,
        seat = 0,
        remaining_tiles = remaining_tiles,
    )


# 確認 Rules 的槓牌類型能正確傳到 Strategy
@pytest.mark.parametrize("kong_type", ["ming", "an", "jia"])
def test_kong_type_is_preserved(kong_type):
    action = Action(action_type = ActionType.KONG, tile_id = 33, kong_type = kong_type)
    legal = action_to_legal_action(action)

    assert legal.action == ActionType.KONG
    assert legal.kong_type == kong_type
    assert legal.tile == 33


# 明槓從自己的暗牌移除三張，並新增一組副露
def test_simulate_ming_kong():
    action = LegalAction(id = "kong_33", action = ActionType.KONG, tile = 33, kong_type = "ming")
    remaining, added = simulate_kong(MING_HAND, action, ())

    assert len(remaining) == len(MING_HAND) - 3
    assert remaining.count(33) == 0
    assert added == 1


# 暗槓從自己手牌移除四張，並新增一組面子
def test_simulate_an_kong():
    action = LegalAction(id = "kong_33", action = ActionType.KONG, tile = 33, kong_type = "an")
    remaining, added = simulate_kong(AN_HAND, action, ())

    assert len(remaining) == len(AN_HAND) - 4
    assert added == 1


# 加槓只移除手上一張，不能重複增加副露面子數
def test_simulate_jia_kong():
    action = LegalAction(id = "kong_33", action = ActionType.KONG, tile = 33, kong_type = "jia")
    remaining, added = simulate_kong(JIA_HAND, action, ((33, 33, 33),))

    assert len(remaining) == len(JIA_HAND) - 1
    assert remaining.count(33) == 0
    assert added == 0


# 用真正 Rules 產生合法明槓、碰及 PASS，評估有利的補牌機會
def test_ming_kong_is_selected():
    rules_actions = LegalActionGenerator().get_response_actions(
        hand = list(MING_HAND), target_tile = 33, is_previous_player = False,
    )
    legal_actions = actions_to_legal_actions(rules_actions)
    decision = KongEfficiencyPolicy().decide(make_observation(MING_HAND), legal_actions)

    assert decision.action.action == ActionType.KONG
    assert decision.action.kong_type == "ming"
    assert decision.action in legal_actions
    assert "replacement_draw = pending" in decision.reason


# 自己摸牌後有四張相同牌時，評估暗槓和正常棄牌
def test_an_kong_is_selected():
    rules_actions = LegalActionGenerator().get_turn_player_actions(hand = list(AN_HAND))
    legal_actions = actions_to_legal_actions(rules_actions)
    decision = KongEfficiencyPolicy().decide(make_observation(AN_HAND), legal_actions)

    assert decision.action.action == ActionType.KONG
    assert decision.action.kong_type == "an"
    assert decision.action in legal_actions


# 原有碰牌已副露時，可將碰牌升級成加槓
def test_jia_kong_is_selected():
    rules_actions = LegalActionGenerator().get_turn_player_actions(
        hand = list(JIA_HAND), melded_pongs = [33],
    )
    legal_actions = actions_to_legal_actions(rules_actions)
    observation = make_observation(JIA_HAND, melds = ((33, 33, 33),))
    decision = KongEfficiencyPolicy().decide(observation, legal_actions)

    assert decision.action.action == ActionType.KONG
    assert decision.action.kong_type == "jia"
    assert decision.action in legal_actions


# 牌牆已經到保留張數時，不主動槓牌，優先 PASS
def test_kong_pass_when_wall_is_low():
    rules_actions = LegalActionGenerator().get_response_actions(
        hand = list(MING_HAND), target_tile = 33, is_previous_player = False,
    )
    legal_actions = actions_to_legal_actions(rules_actions)
    decision = KongEfficiencyPolicy().decide(make_observation(MING_HAND, remaining_tiles = 16), legal_actions)

    assert decision.action.action == ActionType.PASS


# 槓牌種類不明時不自行猜測，保留 PASS 避免錯誤決策
def test_unknown_kong_type_uses_pass():
    legal_actions = [
        LegalAction(id = "kong_33", action = ActionType.KONG, tile = 33),
        LegalAction(id = "pass", action = ActionType.PASS),
    ]
    decision = KongEfficiencyPolicy().decide(make_observation(MING_HAND), legal_actions)

    assert decision.action.action == ActionType.PASS


# WIN 仍然比所有槓牌與過牌優先
def test_win_has_highest_priority():
    legal_actions = [
        LegalAction(id = "kong_33", action = ActionType.KONG, tile = 33, kong_type = "ming"),
        LegalAction(id = "win_33", action = ActionType.WIN, tile = 33),
        LegalAction(id = "pass", action = ActionType.PASS),
    ]
    decision = KongEfficiencyPolicy().decide(make_observation(MING_HAND), legal_actions)

    assert decision.action.action == ActionType.WIN


# 沒有槓牌時，D4 策略保持 D3 原本的吃碰與 PASS 決策
def test_no_kong_keeps_d3_decision():
    rules_actions = LegalActionGenerator().get_response_actions(
        hand = list(MING_HAND), target_tile = 33, is_previous_player = False,
    )
    legal_actions = [
        action for action in actions_to_legal_actions(rules_actions)
        if action.action != ActionType.KONG
    ]
    observation = make_observation(MING_HAND)
    d3 = MeldEfficiencyPolicy().decide(observation, legal_actions)
    d4 = KongEfficiencyPolicy().decide(observation, legal_actions)

    assert d4.action == d3.action


# 非法明槓、加槓及沒有合法動作都應拒絕
def test_invalid_kong_is_rejected():
    ming = LegalAction(id = "kong_33", action = ActionType.KONG, tile = 33, kong_type = "ming")
    jia = LegalAction(id = "kong_33", action = ActionType.KONG, tile = 33, kong_type = "jia")

    with pytest.raises(ValueError):
        simulate_kong(JIA_HAND, ming, ())

    with pytest.raises(ValueError):
        simulate_kong(JIA_HAND, jia, ())

    with pytest.raises(ValueError):
        KongEfficiencyPolicy().decide(make_observation(MING_HAND), [])