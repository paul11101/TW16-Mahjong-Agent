from dataclasses import replace
import pytest

from src.common.schemas import ActionType
from src.rules.legal_actions import LegalActionGenerator
from src.strategy.action_policy import ActionPolicy
from src.strategy.adapters import actions_to_legal_actions
from src.strategy.interfaces import LegalAction
from src.strategy.meld_policy import evaluate_meld, simulate_meld
from tests.test_strategy_action_policy import (
    CHI_HAND, PONG_HAND, MING_HAND, make_discards, make_observation, make_pass,
)
from tests.test_strategy_reaction_comparison import CASES


# 全部有效進張已可見時，不主動吃碰槓
@pytest.mark.parametrize("with_scores", [False, True])
@pytest.mark.parametrize("hand, action, river", [
    (CHI_HAND, LegalAction("chi", ActionType.CHI, 5, (3, 4, 5)), (5,) * 4 + (8,) * 4),
    (PONG_HAND, LegalAction("pong", ActionType.PONG, 33, (33,) * 3), (33,) + (5,) * 4 + (8,) * 4),
    (MING_HAND, LegalAction("kong", ActionType.KONG, 33, (33,) * 4, "ming"), (33,) + (20,) * 4),
])
def test_exhausted_meld_uses_pass(hand, action, river, with_scores):
    obs = replace(make_observation(hand), discards=((), (), (), river), current_player=3)
    passed = make_pass()
    result = ActionPolicy(include_candidate_scores=with_scores).decide(obs, [action, passed])
    assert result.action is passed
    if with_scores:
        candidate = result.candidate_evaluations[0]
        assert candidate.scorable and candidate.effective_draws == 0
        assert candidate.unseen_upper_bound == 0


# 吃牌計畫與真正吃完後的棄牌，必須保留相同的活張
def test_meld_plan_matches_following_discard():
    hand = (0, 1, 2, 9, 10, 11, 18, 19, 20, 3, 4, 5, 6, 7, 27, 33)
    chi = LegalAction("chi_6_7_8", ActionType.CHI, 8, (6, 7, 8))
    obs = replace(make_observation(hand), discards=((), (), (), (8, 33, 33, 33)), current_player=3)
    result = ActionPolicy().decide(obs, [chi, make_pass()])
    candidate = result.candidate_evaluations[0]
    assert result.action is chi
    assert candidate.next_discard == 33 and candidate.unseen_upper_bound == 3
    assert "next_discard = 33" in result.reason
    assert evaluate_meld(hand, chi, 0)[2] == 27  # 舊介面仍保留原本結果

    # 被吃走的河牌移到副露，不重複計算公開張數
    after = replace(
        obs, hand=simulate_meld(hand, chi), melds=((chi.tiles,), (), (), ()),
        discards=((), (), (), (33, 33, 33)), current_player=0,
    )
    following = ActionPolicy().decide(after, make_discards(after.hand))
    assert following.action.tile == candidate.next_discard


# 多種吃法之間，選擇仍有未見進張的方案
@pytest.mark.parametrize("reverse", [False, True])
def test_chi_uses_public_information(reverse):
    obs = replace(
        make_observation(CHI_HAND), discards=((), (), (), (5,) * 4 + (8,) * 4),
        current_player=3,
    )
    actions = actions_to_legal_actions(LegalActionGenerator().get_response_actions(
        hand=list(CHI_HAND), target_tile=5, is_previous_player=True,
    ))
    if reverse:
        actions.reverse()
    result = ActionPolicy().decide(obs, actions)
    assert result.action.id == "chi_5_6_7"
    assert result.action in actions


# 槓牌必須與公開資訊棄牌結果比較，不能只比進張種類數
def test_kong_does_not_replace_better_discard():
    hand = (9, 9, 9, 9, 13, 14, 15, 2, 3, 4, 6, 7, 8, 16, 30, 33, 1)
    kong = LegalAction("kong_9", ActionType.KONG, 9, (9,) * 4, "an")
    actions = [kong, *make_discards(hand)]
    result = ActionPolicy().decide(make_observation(hand), actions)
    assert result.action.id == "discard_30"
    scores = {item.action_id: item for item in result.candidate_evaluations}
    selected, rejected = scores[result.action.id], scores[kong.id]
    assert selected.shanten == rejected.shanten == 2
    assert selected.effective_draws == rejected.effective_draws == 16
    assert selected.unseen_upper_bound == 54
    assert rejected.unseen_upper_bound == 53


# 鎖定 v1 的版本與原本八組固定牌局結果
@pytest.mark.parametrize("case_name, expected", [
    ("win", "win_3"), ("chi", "chi_3_4_5"), ("pong", "pong_33"), ("pass", "pass"),
    ("ming_kong", "kong_33"), ("an_kong", "kong_33"), ("jia_kong", "kong_33"),
    ("low_wall", "pass"),
])
def test_baseline_v1_fixed_cases(case_name, expected):
    obs, actions = CASES[case_name]
    policy = ActionPolicy()
    result = policy.decide(obs, actions)
    assert policy.strategy_version == "baseline_v1"
    assert result.action.id == expected
    assert result.action in actions
    assert policy.decide(obs, actions) == result