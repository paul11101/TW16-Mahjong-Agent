from src.strategy.baseline import BaselinePolicy, RandomPolicy
from src.strategy.interfaces import (ActionType, LegalAction, Observation,)
import pytest


# 建立固定的測試牌局狀態，供所有策略測試共用
def make_observation() -> Observation:
    return Observation(
        hand=(0, 1, 2, 3, 4, 5, 9, 10, 11, 18, 19, 20, 27, 27, 31, 31),
        discards=((), (), (), ()),
        melds=((), (), (), ()),
        flowers=((), (), (), ()),
        current_player=0,
        seat=0,
        remaining_tiles=80,
    )


# 測試 BaselinePolicy 在可以胡牌時，是否優先選擇 WIN
def test_baseline_prefers_win():
    observation = make_observation()

    legal_actions = [
        LegalAction(id="discard_3", action=ActionType.DISCARD, tile=3,),
        LegalAction(id="win", action=ActionType.WIN,),
    ]

    policy = BaselinePolicy()
    decision = policy.decide(observation, legal_actions)

    assert decision.action.id == "win"
    assert decision.action.action == ActionType.WIN


# 測試無法胡牌時，是否選擇第一個合法的 DISCARD
def test_baseline_selects_first_discard():
    observation = make_observation()

    legal_actions = [
        LegalAction(id="discard_3", action=ActionType.DISCARD, tile=3,),
        LegalAction(id="discard_8", action=ActionType.DISCARD, tile=8,),
    ]

    policy = BaselinePolicy()
    decision = policy.decide(observation, legal_actions)

    assert decision.action.id == "discard_3"
    assert decision.action.tile == 3


# 測試沒有 WIN 或 DISCARD 時，是否依目前 baseline 規則選擇 PASS
def test_baseline_selects_pass():
    observation = make_observation()

    legal_actions = [
        LegalAction(
            id="pong_27",
            action=ActionType.PONG,
            tile=27,
            tiles=(27, 27, 27),
        ),
        LegalAction(id="pass", action=ActionType.PASS),
    ]

    policy = BaselinePolicy()
    decision = policy.decide(observation, legal_actions)

    assert decision.action.action == ActionType.PASS


# 測試 RandomPolicy 選出的動作一定來自 LegalActions
def test_random_policy_returns_legal_action():
    observation = make_observation()

    legal_actions = [
        LegalAction(id="discard_3", action=ActionType.DISCARD, tile=3,),
        LegalAction(id="discard_8", action=ActionType.DISCARD, tile=8,),
    ]

    policy = RandomPolicy()
    decision = policy.decide(observation, legal_actions)

    assert decision.action in legal_actions


# 測試沒有任何合法動作時，BaselinePolicy 是否正確拋出 ValueError
def test_baseline_rejects_empty_legal_action():
    observation = make_observation()
    policy = BaselinePolicy()

    with pytest.raises(ValueError):
        policy.decide(observation, [])