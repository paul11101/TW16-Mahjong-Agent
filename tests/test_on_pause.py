"""GameRunner 的 on_pause 回呼：暫停時被呼叫，回呼出錯不影響流程。

執行方式（專案根目錄）：
    python -m tests.test_on_pause
或
    python -m pytest tests/test_on_pause.py -v
"""

from src.control.game_runner import PHASE_MY_TURN
from tests._runner import run_module
from tests.test_game_runner import make, result, seq, snap


def _failing_turn(s):
    return result(ok=False, clicked=True, error="ACTION_TIMEOUT")


def test_on_pause_called_with_error():
    calls = []
    runner, _ = make(seq([snap(PHASE_MY_TURN, "a")]), _failing_turn, on_pause=calls.append)
    summary = runner.run()

    assert calls == ["ACTION_TIMEOUT"]
    assert summary.interventions == 1


def test_on_pause_exception_does_not_break_run():
    def boom(error):
        raise OSError("存檔失敗")

    runner, _ = make(seq([snap(PHASE_MY_TURN, "a")]), _failing_turn, on_pause=boom)
    summary = runner.run()

    assert summary.interventions == 1 and summary.error_codes == {"ACTION_TIMEOUT": 1}


if __name__ == "__main__":
    run_module(globals(), "test_on_pause")