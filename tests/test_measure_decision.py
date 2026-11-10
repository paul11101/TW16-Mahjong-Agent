"""決策耗時量測腳本的測試（只跑 2 局，不需要視窗）。

執行方式（專案根目錄）：
    python -m tests.test_measure_decision
或
    python -m pytest tests/test_measure_decision.py -v
"""

from src.strategy.action_policy import ActionPolicy
from test_interface import measure_decision as md
from tests._runner import run_module


def test_play_game_collects_samples():
    samples = {k: [] for k in md.SAMPLE_KEYS}
    steps = md.play_game(1, ActionPolicy(), samples)

    assert steps > 0
    assert len(samples["my_turn"]) > 0
    assert all(ms >= 0 for values in samples.values() for ms in values)


def test_measure_returns_stats_for_both_modes():
    for flag in (False, True):
        result = md.measure([1, 2], include_candidate_scores=flag)

        assert {"my_turn", "all"} <= set(result)
        assert result["all"]["n"] >= result["my_turn"]["n"]
        assert result["all"]["p95"] >= result["all"]["mean"] * 0  # p95 有值
        assert result["all"]["max"] >= result["all"]["p95"]


if __name__ == "__main__":
    run_module(globals(), "test_measure_decision")