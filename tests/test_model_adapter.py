"""W9 模型轉接層測試：假 backend、SimTable 整局、（有 torch 時）真的 TorchScript checkpoint。

執行方式（專案根目錄）：
    python -m tests.test_model_adapter
或
    python -m pytest tests/test_model_adapter.py -v
"""

import argparse
import math
import random

import pytest

from src.common.schemas import ActionType
from src.control.model_adapter import (
    ModelPolicy,
    add_policy_args,
    build_policy,
    policy_from_args,
)
from src.strategy.action_mask import ACTION_SPACE_SIZE, action_to_index
from src.strategy.action_policy import ActionPolicy
from src.strategy.interfaces import LegalAction, Observation
from test_interface import measure_decision as md
from test_interface.live_game import build_parser
from tests._runner import run_module

HAND = (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 18, 19, 20, 27, 33)
OBS = Observation(
    hand=HAND, discards=((),) * 4, melds=((),) * 4, flowers=((),) * 4,
    current_player=0, seat=0, remaining_tiles=80,
)
ACTIONS = (
    LegalAction("discard_27", ActionType.DISCARD, 27),
    LegalAction("discard_33", ActionType.DISCARD, 33),
)


class FixedBackend:
    def __init__(self, scores=None, default=-1.0, length=ACTION_SPACE_SIZE):
        self.scores, self.default, self.length = scores or {}, default, length

    def predict(self, features, mask):
        assert len(features) == 555 and len(mask) == ACTION_SPACE_SIZE
        return [self.scores.get(i, self.default) for i in range(self.length)]


class BrokenBackend:
    def predict(self, features, mask):
        raise RuntimeError("model crashed")


class RandomBackend:
    def __init__(self, seed):
        self.rng = random.Random(seed)

    def predict(self, features, mask):
        return [self.rng.random() for _ in range(ACTION_SPACE_SIZE)]


def test_picks_highest_legal_score_and_ignores_illegal_indices():
    backend = FixedBackend({5: 99.0, action_to_index(ACTIONS[0]): 1.0, action_to_index(ACTIONS[1]): 2.0})
    policy = ModelPolicy(backend, model_version="t1")
    decision = policy.decide(OBS, ACTIONS)

    assert decision.action.id == "discard_33" and decision.score == pytest.approx(1 / (1 + math.exp(-1)))
    assert decision.reason.startswith("model t1")
    assert [e.action_id for e in decision.candidate_evaluations] == ["discard_27", "discard_33"]
    assert [e.score for e in decision.candidate_evaluations] == [1.0, 2.0]
    assert len(decision.candidate_scores) == 2  # 共用 schema 也有分數
    assert policy.model_decisions == 1 and policy.fallback_decisions == 0


def test_tie_keeps_legal_action_order():
    decision = ModelPolicy(FixedBackend(default=0.5)).decide(OBS, ACTIONS)
    assert decision.action.id == "discard_27"
    assert ModelPolicy(FixedBackend(default=0.5)).decide(OBS, ACTIONS[::-1]).action.id == "discard_33"


def test_failures_fall_back_to_baseline():
    expected = ActionPolicy().decide(OBS, ACTIONS)
    nan_legal = FixedBackend({action_to_index(ACTIONS[0]): math.nan})

    for backend in (BrokenBackend(), FixedBackend(length=10), nan_legal):
        policy = ModelPolicy(backend)
        decision = policy.decide(OBS, ACTIONS)

        assert decision.action == expected.action
        assert decision.reason.startswith("fallback (")
        assert policy.fallback_decisions == 1 and policy.model_decisions == 0
        assert sum(policy.fallback_reasons.values()) == 1


def test_nan_on_illegal_index_is_not_a_failure():
    policy = ModelPolicy(FixedBackend({0: math.nan, action_to_index(ACTIONS[1]): 3.0}))
    assert policy.decide(OBS, ACTIONS).action.id == "discard_33"
    assert policy.fallback_decisions == 0


def test_unsupported_action_falls_back_then_baseline_rejects():
    draw = LegalAction("draw", ActionType.DRAW_TILE, 3)
    policy = ModelPolicy(FixedBackend())
    with pytest.raises(ValueError, match="unsupported decision action"):
        policy.decide(OBS, (draw,))
    assert policy.fallback_decisions == 1  # 先試過模型、退回 baseline，baseline 拒絕才往外拋


def test_empty_actions_rejected():
    with pytest.raises(ValueError, match="empty"):
        ModelPolicy(FixedBackend()).decide(OBS, [])


def test_version_and_describe():
    policy = ModelPolicy(FixedBackend(), model_version="bc_v1-ab12cd34", checkpoint_sha256="f" * 64)
    assert policy.strategy_version == "model_bc_v1-ab12cd34"
    policy.decide(OBS, ACTIONS)
    text = policy.describe()
    assert "model_bc_v1-ab12cd34" in text and "模型決策 1 次" in text and "ffffffffffff" in text


def test_full_game_with_model_policy_has_no_fallback():
    policy = ModelPolicy(RandomBackend(1), model_version="rand")
    samples = {k: [] for k in md.SAMPLE_KEYS}
    steps = md.play_game(3, policy, samples)

    total = len(samples["my_turn"]) + len(samples["reaction"])
    assert steps > 0 and total > 0
    assert policy.fallback_decisions == 0 and policy.model_decisions == total


def test_factory_and_args():
    assert isinstance(build_policy("baseline"), ActionPolicy)
    with pytest.raises(ValueError):
        build_policy("model")
    with pytest.raises(FileNotFoundError):
        build_policy("model", checkpoint="nope/none.pt")
    with pytest.raises(ValueError):
        build_policy("magic")

    parser = argparse.ArgumentParser()
    add_policy_args(parser)
    assert isinstance(policy_from_args(parser.parse_args([])), ActionPolicy)
    with pytest.raises(RuntimeError, match="策略載入失敗"):
        policy_from_args(parser.parse_args(["--policy", "model"]))


def test_live_parser_defaults_to_baseline():
    args = build_parser().parse_args([])
    assert args.policy == "baseline" and args.checkpoint is None and args.device == "cpu"


def test_real_torchscript_checkpoint(tmp_path):
    try:
        import torch
    except ImportError:
        print("  （沒有 torch，略過 TorchScript 測試）")
        return

    class Net(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.fc = torch.nn.Linear(555, ACTION_SPACE_SIZE)

        def forward(self, x):
            return self.fc(x)

    path = tmp_path / "tiny_bc.pt"
    torch.jit.trace(Net(), torch.zeros(1, 555)).save(str(path))

    policy = build_policy("model", checkpoint=path)
    decision = policy.decide(OBS, ACTIONS)

    assert decision.action in ACTIONS
    assert policy.model_decisions == 1 and policy.fallback_decisions == 0
    assert policy.strategy_version.startswith("model_tiny_bc-") and len(policy.checkpoint_sha256) == 64


if __name__ == "__main__":
    run_module(globals(), "test_model_adapter")