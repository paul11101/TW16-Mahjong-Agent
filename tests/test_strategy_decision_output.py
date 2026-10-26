import json
from dataclasses import replace

import pytest

from src.common.schemas import ActionType, Decision as SchemaDecision
from src.control.pipeline import EventIds, _decide_and_log
from src.strategy.action_policy import ActionPolicy
from src.strategy.candidate_scoring import CandidateEvaluation as ExportedEvaluation
from src.strategy.interfaces import CandidateEvaluation, Decision, LegalAction
from tests.test_strategy_action_policy import DISCARD_HAND, make_discards, make_observation
from tests.test_strategy_reaction_comparison import CASES


# 重用既有八組固定牌局，確認輸出整合不改變選牌
@pytest.mark.parametrize("case_name", tuple(CASES))
def test_fixed_cases_keep_original_selection(case_name):
    observation, actions = CASES[case_name]
    original = ActionPolicy(include_candidate_scores=False).decide(observation, actions)
    result = ActionPolicy().decide(observation, actions)

    assert (result.action, result.score, result.reason) == (
        original.action, original.score, original.reason
    )
    assert [item.action_id for item in result.candidate_evaluations] == [a.id for a in actions]
    assert result.candidate_scores
    assert result == ActionPolicy().decide(observation, actions)


# 原本三個參數的建構方式與舊匯入位置仍可使用
def test_existing_interfaces_remain_compatible():
    action = LegalAction(id="pass", action=ActionType.PASS)
    result = Decision(action, 0.0, "legacy")
    assert result.candidate_evaluations == ()
    assert result.candidate_scores == ()
    assert ExportedEvaluation is CandidateEvaluation


# 候選分數再高，也不取代既有選牌結果
def test_scores_are_attached_once_without_reselecting(monkeypatch):
    observation, actions = CASES["win"]
    policy = ActionPolicy()
    evaluations = policy.score_candidates(observation, actions)
    evaluations = tuple(replace(item, score=999.0) for item in evaluations)
    calls = []

    def fake_scores(*args):
        calls.append(args)
        return evaluations

    monkeypatch.setattr(policy, "score_candidates", fake_scores)
    result = policy.decide(observation, actions)
    assert len(calls) == 1
    assert result.action.action == ActionType.WIN
    assert result.score == 1.0
    assert result.reason == "win is available"
    assert result.candidate_evaluations == evaluations


# 關閉候選輸出時，不進行額外評分
def test_disabled_scores_skip_evaluation(monkeypatch):
    policy = ActionPolicy(include_candidate_scores=False)

    def unexpected(*args):
        raise AssertionError("candidate scoring should not run")

    monkeypatch.setattr(policy, "score_candidates", unexpected)
    observation = make_observation(DISCARD_HAND)
    result = policy.decide(observation, make_discards(DISCARD_HAND))
    assert result.candidate_scores == ()


# 共用 Schema 只放有效分數，完整診斷仍保留在 Decision
def test_unscorable_candidate_is_preserved():
    observation = make_observation(DISCARD_HAND)
    invalid = LegalAction(id="unknown_kong", action=ActionType.KONG, tile=33)
    actions = [invalid, *make_discards(DISCARD_HAND)]
    result = ActionPolicy().decide(observation, actions)
    failed = next(item for item in result.candidate_evaluations if item.action_id == invalid.id)
    assert not failed.scorable and failed.score is None and failed.reason
    assert invalid.id not in {item.action_id for item in result.candidate_scores}
    assert result.action.action == ActionType.DISCARD


# 驗證 Strategy 到整合事件的 JSON 輸出
def test_pipeline_exports_scores_and_diagnostics():
    class Logger:
        def __init__(self):
            self.events = []

        def log_event(self, event, **kwargs):
            self.events.append(event)

    observation = make_observation(DISCARD_HAND)
    invalid = LegalAction(id="unknown_kong", action=ActionType.KONG, tile=33)
    actions = [invalid, *make_discards(DISCARD_HAND)]
    logger = Logger()
    result, _, _, _ = _decide_and_log(
        ActionPolicy(), observation, actions, game_id="decision_output",
        ids=EventIds(), legal_event_id="legal_001", logger=logger,
    )
    event = json.loads(logger.events[0].model_dump_json())
    payload = event["payload"]
    restored = SchemaDecision.model_validate(payload)

    assert restored.selected_action.action_id == result.action.id
    assert restored.reason == result.reason
    assert [item.action_id for item in restored.candidate_scores] == [
        item.action_id for item in result.candidate_scores
    ]
    failed = next(
        item for item in event["metadata"]["candidate_evaluations"]
        if item["action_id"] == invalid.id
    )
    assert failed["score"] is None and failed["scorable"] is False
    assert failed["reason"]