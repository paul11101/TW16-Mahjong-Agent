from time import perf_counter

import pytest

from src.common.schemas import ActionType
from src.rules.legal_actions import LegalActionGenerator
from src.strategy.adapters import actions_to_legal_actions
from src.strategy.baseline import BaselinePolicy
from src.strategy.interfaces import LegalAction, Observation
from src.strategy.kong_policy import KongEfficiencyPolicy
from src.strategy.meld_policy import MeldEfficiencyPolicy


# 固定測試牌型，確保不同策略使用相同的輸入資料
WIN_HAND = (0, 1, 2, 3, 3, 4, 5, 6, 9, 10, 11, 18, 19, 20, 27, 27)
CHI_HAND = (0, 1, 2, 9, 10, 11, 18, 19, 20, 27, 27, 3, 4, 6, 7, 33)
PONG_HAND = (0, 1, 2, 9, 10, 11, 18, 19, 20, 27, 27, 33, 33, 6, 7, 24)
PASS_HAND = (0, 1, 2, 3, 4, 5, 9, 10, 11, 18, 19, 20, 27, 27, 6, 7)

MING_HAND = (0, 1, 2, 3, 4, 5, 9, 10, 11, 18, 19, 27, 27, 33, 33, 33)
AN_HAND = (0, 1, 2, 3, 4, 5, 9, 10, 11, 18, 19, 20, 27, 33, 33, 33, 33)
JIA_HAND = (0, 1, 2, 3, 4, 5, 9, 10, 11, 18, 19, 20, 27, 33)


# 定義三個需要比較的策略版本
POLICIES = (
    ("Baseline", BaselinePolicy),
    ("Meld", MeldEfficiencyPolicy),
    ("Kong", KongEfficiencyPolicy),
)


# 建立測試用的 Observation
def make_observation(hand, melds = (), remaining_tiles = 80, current_player = 3):
    return Observation(
        hand = tuple(hand),
        discards = ((), (), (), ()),
        melds = (tuple(melds), (), (), ()),
        flowers = ((), (), (), ()),
        current_player = current_player,
        seat = 0,
        remaining_tiles = remaining_tiles,
    )


# 使用 Rules 產生其他玩家出牌後的合法反應
def make_reaction_actions(hand, target_tile, is_previous_player = False, can_win = False):
    rules_actions = LegalActionGenerator().get_response_actions(
        hand = list(hand),
        target_tile = target_tile,
        is_previous_player = is_previous_player,
        can_win_honin = can_win,
    )

    return tuple(actions_to_legal_actions(rules_actions))


# 使用 Rules 產生自己回合的合法動作
def make_turn_actions(hand, melded_pongs = ()):
    rules_actions = LegalActionGenerator().get_turn_player_actions(
        hand = list(hand),
        melded_pongs = list(melded_pongs),
    )

    return tuple(actions_to_legal_actions(rules_actions))


# 建立不同反應情境，確保策略使用完全相同的測試資料
def make_cases():
    return {
        "win": (
            make_observation(WIN_HAND),
            make_reaction_actions(WIN_HAND, 3, True, True),
        ),
        "chi": (
            make_observation(CHI_HAND),
            make_reaction_actions(CHI_HAND, 5, True),
        ),
        "pong": (
            make_observation(PONG_HAND),
            make_reaction_actions(PONG_HAND, 33),
        ),
        "pass": (
            make_observation(PASS_HAND),
            make_reaction_actions(PASS_HAND, 27),
        ),
        "ming_kong": (
            make_observation(MING_HAND),
            make_reaction_actions(MING_HAND, 33),
        ),
        "an_kong": (
            make_observation(AN_HAND, current_player = 0),
            make_turn_actions(AN_HAND),
        ),
        "jia_kong": (
            make_observation(
                JIA_HAND,
                melds = ((33, 33, 33),),
                current_player = 0,
            ),
            make_turn_actions(JIA_HAND, melded_pongs = (33,)),
        ),
        "low_wall": (
            make_observation(MING_HAND, remaining_tiles = 16),
            make_reaction_actions(MING_HAND, 33),
        ),
    }


CASES = make_cases()


# 確認不同策略都只能選擇 Rules 提供的合法動作
@pytest.mark.parametrize("case_name", tuple(CASES))
@pytest.mark.parametrize("policy_name, policy_class", POLICIES)
def test_policies_choose_legal_actions(case_name, policy_name, policy_class):
    observation, legal_actions = CASES[case_name]

    decision = policy_class().decide(observation, legal_actions)

    assert decision.action in legal_actions
    assert isinstance(decision.score, (int, float))
    assert isinstance(decision.reason, str)
    assert decision.reason


# 驗證完整反應策略在不同情境下的預期選擇
@pytest.mark.parametrize(
    "case_name, expected_action",
    [
        ("win", ActionType.WIN),
        ("chi", ActionType.CHI),
        ("pong", ActionType.PONG),
        ("pass", ActionType.PASS),
        ("ming_kong", ActionType.KONG),
        ("an_kong", ActionType.KONG),
        ("jia_kong", ActionType.KONG),
        ("low_wall", ActionType.PASS),
    ],
)
def test_reaction_policy_expected_decisions(case_name, expected_action):
    observation, legal_actions = CASES[case_name]

    decision = KongEfficiencyPolicy().decide(observation, legal_actions)

    assert decision.action.action == expected_action
    assert decision.action in legal_actions


# 沒有槓牌選項時，完整策略應保留原本吃碰策略的決策結果
@pytest.mark.parametrize("case_name", ("win", "chi", "pong", "pass"))
def test_reaction_policy_preserves_meld_decisions(case_name):
    observation, legal_actions = CASES[case_name]

    assert all(action.action != ActionType.KONG for action in legal_actions)

    meld_decision = MeldEfficiencyPolicy().decide(observation, legal_actions)
    kong_decision = KongEfficiencyPolicy().decide(observation, legal_actions)

    assert kong_decision.action == meld_decision.action
    assert kong_decision.reason == meld_decision.reason


# 加槓資料不合法時，策略應略過槓牌並選擇 PASS
def test_invalid_kong_falls_back_to_pass():
    legal_actions = (
        LegalAction(
            id = "kong_33",
            action = ActionType.KONG,
            tile = 33,
            kong_type = "jia",
        ),
        LegalAction(id = "pass", action = ActionType.PASS),
    )

    observation = make_observation(MING_HAND)

    decision = KongEfficiencyPolicy().decide(observation, legal_actions)

    assert decision.action.action == ActionType.PASS


# 牌牆不足且沒有其他合法動作時，不得強制執行槓牌
def test_kong_rejected_when_wall_is_low():
    legal_actions = (
        LegalAction(
            id = "kong_33",
            action = ActionType.KONG,
            tile = 33,
            kong_type = "an",
        ),
    )

    observation = make_observation(
        AN_HAND,
        remaining_tiles = 16,
        current_player = 0,
    )

    with pytest.raises(ValueError, match = "no safe legal action available"):
        KongEfficiencyPolicy().decide(observation, legal_actions)


# 槓牌類型不明且不存在其他選擇時，應明確拒絕
def test_unknown_kong_type_is_rejected():
    legal_actions = (
        LegalAction(
            id = "kong_33",
            action = ActionType.KONG,
            tile = 33,
        ),
    )

    with pytest.raises(ValueError, match = "no safe legal action available"):
        KongEfficiencyPolicy().decide(
            make_observation(MING_HAND),
            legal_actions,
        )


# 牌牆剩餘數量未知時，保留原本的吃碰及 PASS 策略
def test_unknown_wall_preserves_meld_decision():
    legal_actions = make_reaction_actions(MING_HAND, 33)
    observation = make_observation(MING_HAND, remaining_tiles = None)

    meld_decision = MeldEfficiencyPolicy().decide(observation, legal_actions)
    kong_decision = KongEfficiencyPolicy().decide(observation, legal_actions)

    assert kong_decision.action == meld_decision.action
    assert kong_decision.action.action != ActionType.KONG


# KONG 是唯一且安全的合法動作時，仍然可以執行
def test_safe_kong_can_be_selected():
    kong_action = LegalAction(
        id = "kong_33",
        action = ActionType.KONG,
        tile = 33,
        kong_type = "an",
    )

    observation = make_observation(AN_HAND, current_player = 0)

    decision = KongEfficiencyPolicy().decide(observation, (kong_action,))

    assert decision.action == kong_action
    assert decision.action.action == ActionType.KONG


# 確認策略運算不會修改原本的手牌、副露或合法動作
@pytest.mark.parametrize("case_name", tuple(CASES))
def test_reaction_policy_preserves_inputs(case_name):
    observation, legal_actions = CASES[case_name]

    original_hand = observation.hand
    original_melds = observation.melds
    original_actions = tuple(legal_actions)

    KongEfficiencyPolicy().decide(observation, legal_actions)

    assert observation.hand == original_hand
    assert observation.melds == original_melds
    assert tuple(legal_actions) == original_actions


# 對相同牌局執行三種策略，收集動作結果與計算時間
def compare_reaction_policies():
    results = {}
    elapsed = {name: 0.0 for name, _ in POLICIES}

    for case_name, (observation, legal_actions) in CASES.items():
        results[case_name] = {}

        for policy_name, policy_class in POLICIES:
            policy = policy_class()

            started = perf_counter()
            decision = policy.decide(observation, legal_actions)
            elapsed[policy_name] += (perf_counter() - started) * 1000

            assert decision.action in legal_actions

            results[case_name][policy_name] = decision.action.action

    return results, elapsed


# 將三種策略的反應結果及平均耗時輸出成比較表
def print_comparison():
    results, elapsed = compare_reaction_policies()

    print()
    print("Reaction Strategy Comparison")
    print(f"{'Case':<18}{'Baseline':<15}{'Meld':<15}{'Kong':<15}")
    print("-" * 63)

    differences = 0

    for case_name, actions in results.items():
        baseline = actions["Baseline"].value
        meld = actions["Meld"].value
        kong = actions["Kong"].value

        if meld != kong:
            differences += 1

        print(f"{case_name:<18}{baseline:<15}{meld:<15}{kong:<15}")

    print("-" * 63)
    print(f"Cases: {len(results)}")
    print(f"Meld / Kong different decisions: {differences}")

    for policy_name in elapsed:
        average_ms = elapsed[policy_name] / len(results)
        print(f"{policy_name} average decision latency: {average_ms:.3f} ms")

    return results


# 驗證完整策略能保留吃碰胡過牌，同時新增明槓、暗槓、加槓
def test_reaction_policy_comparison():
    results = print_comparison()

    for case_name in ("win", "chi", "pong", "pass"):
        assert results[case_name]["Meld"] == results[case_name]["Kong"]

    for case_name in ("ming_kong", "an_kong", "jia_kong"):
        assert results[case_name]["Kong"] == ActionType.KONG

    assert results["low_wall"]["Kong"] == ActionType.PASS


if __name__ == "__main__":
    print_comparison()