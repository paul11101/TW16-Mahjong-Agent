"""略過的反應回合不算進 max_steps（真實遊戲每次都有反應按鈕出現，卻不點）。

執行方式（專案根目錄）：
    python -m tests.test_game_runner_skips
"""

from src.control.game_runner import PHASE_MY_TURN, PHASE_OVER, PHASE_REACTION
from tests._runner import run_module
from tests.test_game_runner import make, result, seq, snap


def test_skipped_steps_do_not_consume_max_steps():
    observe = seq([snap(PHASE_REACTION, f"r{i}") for i in range(4)] + [snap(PHASE_OVER)])
    runner, _ = make(observe, lambda s: result(skipped=True), max_steps=2)
    summary = runner.run()

    assert summary.finished and summary.reason == "game_over"
    assert summary.skipped == 4 and summary.steps == 4


def test_real_steps_still_limited():
    n = {"i": 0}

    def observe():
        n["i"] += 1
        return snap(PHASE_MY_TURN, n["i"])

    summary = make(observe, lambda s: result(), max_steps=3)[0].run()
    assert summary.reason == "max_steps" and summary.completed == 3


if __name__ == "__main__":
    run_module(globals(), "test_game_runner_skips")