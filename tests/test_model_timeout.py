"""W10：模型逾時、斷路、暖機、TimedPolicy、遮罩與參數的測試。

    python -m tests.test_model_timeout
"""

import argparse
import time

import pytest

from src.control.model_adapter import (
    ModelPolicy,
    ModelTimeoutError,
    TimedPolicy,
    add_policy_args,
    call_with_timeout,
    policy_from_args,
)
from src.strategy.action_mask import ACTION_SPACE_SIZE, build_action_mask
from src.strategy.action_policy import ActionPolicy
from tests._runner import run_module
from tests.test_model_adapter import ACTIONS, OBS, BrokenBackend, FixedBackend


class HangBackend:
    def __init__(self, seconds=0.5):
        self.calls, self.seconds = 0, seconds

    def predict(self, features, mask):
        self.calls += 1
        time.sleep(self.seconds)
        return [0.0] * ACTION_SPACE_SIZE


class CaptureBackend:
    def __init__(self):
        self.masks = []

    def predict(self, features, mask):
        self.masks.append(tuple(mask))
        return [0.0] * ACTION_SPACE_SIZE


def test_call_with_timeout():
    assert call_with_timeout(lambda x: x + 1, 1.0, 2) == 3
    with pytest.raises(ModelTimeoutError):
        call_with_timeout(time.sleep, 0.05, 0.5)
    with pytest.raises(RuntimeError, match="boom"):
        call_with_timeout(lambda: (_ for _ in ()).throw(RuntimeError("boom")), 1.0)


def test_timeout_falls_back_to_baseline():
    policy = ModelPolicy(HangBackend(), timeout=0.05)
    decision = policy.decide(OBS, ACTIONS)

    assert decision.action == ActionPolicy().decide(OBS, ACTIONS).action
    assert policy.timeouts == 1 and policy.fallback_decisions == 1 and policy.model_decisions == 0
    assert any("ModelTimeoutError" in why for why in policy.fallback_reasons)


def test_fast_model_under_timeout_is_used():
    policy = ModelPolicy(FixedBackend(), timeout=1.0)
    policy.decide(OBS, ACTIONS)

    assert policy.model_decisions == 1 and policy.fallback_decisions == 0


def test_backend_exception_through_thread_still_falls_back():
    policy = ModelPolicy(BrokenBackend(), timeout=1.0)
    policy.decide(OBS, ACTIONS)

    assert policy.fallback_decisions == 1 and policy.timeouts == 0
    assert any("RuntimeError" in why for why in policy.fallback_reasons)


def test_circuit_opens_then_retries_model():
    backend = HangBackend()
    policy = ModelPolicy(backend, timeout=0.05, trip_after=2, cooldown=3)

    for _ in range(5):
        policy.decide(OBS, ACTIONS)
    assert policy.timeouts == 2 and policy.trips == 1
    assert backend.calls == 2  # 斷路期間不再呼叫模型
    assert policy.fallback_decisions == 5

    policy.decide(OBS, ACTIONS)  # 冷卻結束：再試一次，失敗就立刻再斷路
    assert backend.calls == 3 and policy.trips == 2 and policy.timeouts == 3


def test_circuit_recovers_when_model_works_again():
    class Flaky:
        def __init__(self):
            self.calls = 0

        def predict(self, features, mask):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("first call fails")
            return [0.0] * ACTION_SPACE_SIZE

    policy = ModelPolicy(Flaky(), trip_after=1, cooldown=2)
    for _ in range(3):
        policy.decide(OBS, ACTIONS)
    assert policy.model_decisions == 0 and policy.fallback_decisions == 3

    policy.decide(OBS, ACTIONS)
    assert policy.model_decisions == 1 and policy.fallback_decisions == 3
    policy.decide(OBS, ACTIONS)
    assert policy.model_decisions == 2  # 已恢復，不再斷路


def test_mask_matches_build_action_mask():
    backend = CaptureBackend()
    ModelPolicy(backend).decide(OBS, ACTIONS)
    assert backend.masks == [build_action_mask(ACTIONS)]


def test_warmup_does_not_count_and_swallows_errors():
    backend = CaptureBackend()
    policy = ModelPolicy(backend)
    policy.warmup()
    assert len(backend.masks) == 1 and policy.model_decisions == 0 and policy.latencies_ms == []

    ModelPolicy(BrokenBackend()).warmup()  # 不拋錯


def test_reset_stats_clears_new_counters():
    policy = ModelPolicy(HangBackend(), timeout=0.05, trip_after=1, cooldown=2)
    policy.decide(OBS, ACTIONS)
    policy.reset_stats()
    assert policy.timeouts == policy.trips == policy.fallback_decisions == 0
    assert policy._skip_left == 0 and "逾時 0" in policy.describe()


def test_invalid_settings_rejected():
    for kwargs in ({"timeout": 0}, {"trip_after": 0}, {"cooldown": -1}):
        with pytest.raises(ValueError):
            ModelPolicy(FixedBackend(), **kwargs)


def test_timed_policy_accumulates_and_pops():
    timed = TimedPolicy(ActionPolicy())
    assert timed.pop_last_ms() is None

    timed.decide(OBS, ACTIONS)
    timed.decide(OBS, ACTIONS)
    first = timed.pop_last_ms()
    assert first is not None and first > 0
    assert timed.pop_last_ms() is None  # 取走後清空

    assert timed.strategy_version == "baseline_v1"
    assert not hasattr(timed, "describe")  # ActionPolicy 沒有，不能被誤判成有


def test_timed_policy_forwards_model_attributes():
    timed = TimedPolicy(ModelPolicy(FixedBackend(), model_version="v"))
    timed.decide(OBS, ACTIONS)
    assert timed.strategy_version == "model_v" and "模型決策 1 次" in timed.describe()


def test_new_policy_args():
    parser = argparse.ArgumentParser()
    add_policy_args(parser)
    args = parser.parse_args(["--model-timeout", "0.2", "--trip-after", "3", "--cooldown", "7"])
    assert (args.model_timeout, args.trip_after, args.cooldown) == (0.2, 3, 7)

    defaults = parser.parse_args([])
    assert defaults.model_timeout == 0.5 and defaults.trip_after == 5 and defaults.cooldown == 20
    assert isinstance(policy_from_args(defaults), ActionPolicy)


if __name__ == "__main__":
    run_module(globals(), "test_model_timeout")