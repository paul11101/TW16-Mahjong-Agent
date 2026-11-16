import json
import sys
from dataclasses import replace

import pytest

from src.common.schemas import ActionType as A
from src.strategy import run_evaluation, run_strategy_review
from src.strategy.action_policy import ActionPolicy
from src.strategy.baseline import RandomPolicy
from src.strategy.evaluation_plan import EvaluationGame
from src.strategy.interfaces import CandidateEvaluation, Decision, LegalAction, Observation
from src.strategy.weighted_policy import DiscardWeights, WeightedPolicy

# 從固定種子 4、座位 1 擷取的公開局面
OBS = Observation(
    hand=(25, 8, 0, 7, 7, 2, 26, 2, 7, 24, 13),
    discards=((16, 19, 0, 8, 5, 29, 22, 33), (19, 16, 23, 27, 31, 27, 10),
              (26, 27, 13, 13, 15, 21), (12, 20, 13, 20, 24, 9, 8)),
    melds=(((14, 15, 16),), ((9, 9, 9), (28, 28, 28)), ((4, 5, 6),),
           ((3, 4, 5), (25, 25, 25), (30, 30, 30))),
    flowers=((41, 34), (40,), (36,), (37,)),
    current_player=1, seat=1, remaining_tiles=46,
)
ACTIONS = tuple(LegalAction(f"discard_{tile}", A.DISCARD, tile) for tile in sorted(set(OBS.hand)))


# 預設權重保留原決策，調整後在同向聽下改選進張種類較多的牌
def test_real_position_and_change_capture():
    original = ActionPolicy().decide(OBS, ACTIONS)
    assert WeightedPolicy().decide(OBS, ACTIONS) == original
    captured = []
    policy = WeightedPolicy(DiscardWeights(1, 2), on_change=lambda *args: captured.append(args))
    chosen = policy.decide(OBS, ACTIONS)
    assert original.action.tile == 8
    assert chosen.action.tile == 0
    assert chosen.score == original.score == -1.0
    assert captured == [(OBS, ACTIONS, original, chosen)]
    assert chosen.candidate_evaluations == original.candidate_evaluations


# 進張加權再高，也不能越過向聽優先順序
def test_weights_cannot_choose_worse_shanten(monkeypatch):
    actions = ACTIONS[:2]
    items = (
        CandidateEvaluation(actions[0].id, 0.0, 0, 1, 1, scorable=True),
        CandidateEvaluation(actions[1].id, -1.0, 1, 20, 70, scorable=True),
    )
    original = Decision(actions[0], 0.0, "test", items)
    policy = WeightedPolicy(DiscardWeights(1, 100))
    monkeypatch.setattr(policy.base, "decide", lambda *_: original)
    assert policy.decide(OBS, actions) == original


# 不把吃碰槓、胡牌或 PASS 拉進棄牌加權比較
@pytest.mark.parametrize("kind", [A.WIN, A.PASS, A.CHI, A.PONG, A.KONG])
def test_other_actions_are_preserved(monkeypatch, kind):
    original = Decision(LegalAction("reaction", kind), 1.0, "test")
    policy = WeightedPolicy(DiscardWeights(1, 2))
    monkeypatch.setattr(policy.base, "decide", lambda *_: original)
    assert policy.decide(OBS, (original.action,) + ACTIONS) is original


@pytest.mark.parametrize("unseen,effective", [
    (-1, 1), (0, 0), (float("nan"), 1), (1, float("inf")),
])
def test_invalid_weights_are_rejected(unseen, effective):
    with pytest.raises(ValueError, match="weight"):
        DiscardWeights(unseen, effective)


# 候選缺少評估時回報失敗，不能偷偷忽略後宣稱完整比較
def test_unscorable_discard_is_rejected(monkeypatch):
    original = ActionPolicy().decide(OBS, ACTIONS)
    broken = replace(original.candidate_evaluations[0], scorable=False)
    original = replace(original, candidate_evaluations=(broken,) + original.candidate_evaluations[1:])
    policy = WeightedPolicy()
    monkeypatch.setattr(policy.base, "decide", lambda *_: original)
    with pytest.raises(ValueError, match="unscorable"):
        policy.decide(OBS, ACTIONS)


# 自訂策略只替換受測座位，對手仍依 Day 1 建立
def test_factory_replaces_only_candidate(monkeypatch):
    game = EvaluationGame(0, 2)
    chosen = RandomPolicy(seed=7)
    play = run_evaluation.play_round

    def checked(state, policies, config, **kwargs):
        assert policies[2] is chosen
        assert all(isinstance(p, RandomPolicy) and p is not chosen
                   for seat, p in enumerate(policies) if seat != 2)
        return play(state, policies, config, **kwargs)

    monkeypatch.setattr(run_evaluation, "play_round", checked)
    report = run_evaluation.evaluate_policy("custom", [game], policy_factory=lambda _: chosen)
    assert report["complete"]
    assert report["completed"] == 1


# 策略建立失敗仍由共用評測器記錄，不算成完成或流局
def test_factory_failure_is_recorded():
    def fail(_):
        raise RuntimeError("factory failed")

    report = run_evaluation.evaluate_policy(
        "custom", [EvaluationGame(0, 0)], policy_factory=fail,
    )
    assert not report["complete"]
    assert report["completed"] == 0 and report["failed"] == 1
    assert report["summary"] is None
    assert "factory failed" in report["errors"][0]["error"]


# 直接執行能保存比較與公開局面，JSON 可重新讀取
def test_main_saves_reproducible_cases(monkeypatch, tmp_path):
    output = tmp_path / "review.json"
    monkeypatch.setattr(sys, "argv", [
        "review", "--seed-start", "4", "--seed-count", "1", "--output", str(output),
    ])
    assert run_strategy_review.main() == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["complete"]
    assert report["baseline"]["completed"] == report["weighted"]["completed"] == 4
    assert report["weights"] == {"unseen": 1.0, "effective": 2.0}
    assert report["cases"]
    for case in report["cases"]:
        assert set(case["observation"]) == set(OBS.__dataclass_fields__)
        assert case["baseline_decision"]["action"] != case["weighted_decision"]["action"]
        assert case["weighted_decision"]["action"] in case["legal_actions"]


# 未完成的對局不能當成完整比較結果
def test_incomplete_rounds_do_not_form_a_complete_comparison():
    report = run_strategy_review.compare_weights(
        [EvaluationGame(0, 0)], DiscardWeights(1, 2), max_steps=1,
    )
    assert not report["complete"]
    assert report["baseline"]["failed"] == report["weighted"]["failed"] == 1
    assert report["baseline"]["summary"] is report["weighted"]["summary"] is None