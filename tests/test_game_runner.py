"""W6 整局流程（GameRunner）測試：假觀察、假回合函式、假時鐘，不需要瀏覽器。

執行方式（專案根目錄）：
    python -m tests.test_game_runner
或
    python -m pytest tests/test_game_runner.py -v
"""

import json

from src.common.logger import AppLogger
from src.common.schemas import ActionReceipt, ActionType
from src.control.controller import AgentController
from src.control.game_runner import (
    PHASE_MY_TURN,
    PHASE_OVER,
    PHASE_REACTION,
    PHASE_WAITING,
    GameRunner,
    Snapshot,
    describe_record,
    load_game_record,
)
from src.control.pipeline import EventIds, TurnResult
from src.strategy.interfaces import Decision, LegalAction
from test_interface.fakes import FakeMouse
from tests._runner import run_module
from tests.helpers import FakeClock


def snap(phase, fp=None):
    return Snapshot(phase=phase, fingerprint=fp, detail={"fp": str(fp)})


def seq(items):
    """依序回傳 items，用完後一直回傳最後一個。"""
    state = {"i": 0}

    def fn():
        i = min(state["i"], len(items) - 1)
        state["i"] += 1
        return items[i]

    return fn


def result(ok=True, clicked=True, error=None, should_stop=False, skipped=False, action="discard_0"):
    if skipped:
        return TurnResult(legal_count=1, skipped=True)
    receipt = ActionReceipt(
        receipt_id="r", game_id="g", event_id="e", decision_id="d",
        success=ok, ui_action_executed=clicked, state_verified=ok and clicked,
        latency_ms=100.0, error_code=error, should_stop=should_stop,
    )
    decision = Decision(action=LegalAction(id=action, action=ActionType.DISCARD, tile=0), score=0.0, reason="t")
    return TurnResult(legal_count=1, decision=decision, receipt=receipt, error=error)


def make(observe, turn, *, reaction=None, logger=None, ids=None, record_path=None, **kw):
    controller = AgentController(game_id="g", mouse=FakeMouse())
    controller.start()
    clock = FakeClock()
    params = dict(poll_interval=0.2, advance_timeout=5.0, idle_timeout=None, pause_timeout=1.0,
                  clock=clock, sleep=clock.sleep)
    params.update(kw)
    fns = {PHASE_MY_TURN: turn, PHASE_REACTION: reaction or turn}
    runner = GameRunner(
        controller, game_id="g", observe_fn=observe, turn_fns=fns, logger=logger,
        next_event_id=ids.next if ids else None, record_path=record_path, **params,
    )
    return runner, controller


def test_full_game_flow_unattended(tmp_path):
    calls = []

    def turn(s):
        calls.append(s.phase)
        return result()

    observe = seq([
        snap(PHASE_MY_TURN, "a"), snap(PHASE_WAITING), snap(PHASE_REACTION, "b"),
        snap(PHASE_WAITING), snap(PHASE_MY_TURN, "c"), snap(PHASE_OVER),
    ])
    path = tmp_path / "g.game.json"
    runner, _ = make(observe, turn, record_path=path)
    summary = runner.run()

    assert summary.finished and summary.reason == "game_over" and summary.unattended
    assert calls == [PHASE_MY_TURN, PHASE_REACTION, PHASE_MY_TURN]
    assert summary.steps == 3 and summary.completed == 3 and summary.failed == 0
    assert summary.ui_actions == 3 and summary.ui_success == 3 and summary.ui_success_rate == 1.0

    data = load_game_record(path)
    assert data["complete"] is True and len(data["steps"]) == 3
    assert data["summary"]["finished"] is True
    assert "#002" in describe_record(data)


def test_same_screen_is_not_clicked_twice():
    calls = []

    def turn(s):
        calls.append(1)
        return result()

    # 畫面「a」連續出現 4 次（動作後畫面還沒更新），之後才前進
    observe = seq([snap(PHASE_MY_TURN, "a")] * 4 + [snap(PHASE_WAITING), snap(PHASE_OVER)])
    summary = make(observe, turn)[0].run()

    assert len(calls) == 1
    assert summary.finished and summary.interventions == 0


def test_not_advanced_pauses_instead_of_reclicking():
    calls = []

    def turn(s):
        calls.append(1)
        return result()

    runner, controller = make(seq([snap(PHASE_MY_TURN, "a")]), turn)
    summary = runner.run()

    assert len(calls) == 1  # 沒有重複點擊
    assert summary.reason == "pause_timeout" and not summary.finished
    assert summary.interventions == 1
    assert summary.error_codes == {"NOT_ADVANCED": 1}
    assert controller.is_stopped


def test_clicked_but_failed_pauses_without_auto_retry():
    calls = []

    def turn(s):
        calls.append(1)
        return result(ok=False, clicked=True, error="ACTION_TIMEOUT")

    summary = make(seq([snap(PHASE_MY_TURN, "a")]), turn)[0].run()

    assert len(calls) == 1  # 已經點過，不自動再點
    assert summary.interventions == 1 and summary.failed == 1
    assert summary.error_codes == {"ACTION_TIMEOUT": 1}
    assert summary.ui_actions == 1 and summary.ui_success == 0  # 失敗留在分母


def test_failure_without_click_retries_automatically():
    calls = []

    def turn(s):
        calls.append(1)
        if len(calls) == 1:
            return result(ok=False, clicked=False, error="TILE_NOT_FOUND")
        return result()

    observe = seq([snap(PHASE_MY_TURN, "a")] * 2 + [snap(PHASE_WAITING), snap(PHASE_OVER)])
    summary = make(observe, turn)[0].run()

    assert len(calls) == 2 and summary.finished
    assert summary.failed == 1 and summary.completed == 1
    assert summary.interventions == 0
    assert summary.error_codes == {"TILE_NOT_FOUND": 1}


def test_max_step_attempts_stops():
    def turn(s):
        return result(ok=False, clicked=False, error="TILE_NOT_FOUND")

    runner, controller = make(seq([snap(PHASE_MY_TURN, "a")]), turn, max_step_attempts=3)
    summary = runner.run()

    assert summary.reason == "max_attempts" and summary.failed == 3
    assert controller.is_stopped


def test_state_mismatch_pauses_for_human():
    def turn(s):
        return TurnResult(legal_count=0, error="STATE_MISMATCH")

    summary = make(seq([snap(PHASE_MY_TURN, "a")]), turn)[0].run()

    assert summary.interventions == 1 and summary.failed == 1
    assert summary.error_codes == {"STATE_MISMATCH": 1}


def test_exception_in_turn_is_recorded_and_pauses():
    def turn(s):
        raise ValueError("策略回傳不合法的動作")

    runner, _ = make(seq([snap(PHASE_MY_TURN, "a")]), turn)
    summary = runner.run()

    assert summary.interventions == 1 and summary.failed == 1
    assert summary.error_codes == {"TURN_EXCEPTION": 1}
    assert "策略回傳不合法的動作" in runner.records[0].detail["exception"]


def test_observe_failures_pause():
    summary = make(lambda: None, lambda s: result(), max_observe_failures=3)[0].run()

    assert summary.interventions == 1 and summary.steps == 0
    assert summary.error_codes == {"OBSERVE_FAILED": 1}


def test_observe_exception_is_treated_as_failure():
    def boom():
        raise OSError("連不到網頁")

    summary = make(boom, lambda s: result(), max_observe_failures=2)[0].run()
    assert summary.error_codes == {"OBSERVE_FAILED": 1}


def test_idle_timeout_pauses():
    summary = make(seq([snap(PHASE_WAITING)]), lambda s: result(), idle_timeout=1.0)[0].run()

    assert summary.error_codes == {"IDLE_TIMEOUT": 1} and summary.interventions == 1


def test_skipped_reaction_does_not_pause():
    calls = []

    def turn(s):
        calls.append(1)
        return result(skipped=True)

    observe = seq([snap(PHASE_REACTION, "a")] * 30 + [snap(PHASE_OVER)])
    summary = make(observe, turn)[0].run()

    assert len(calls) == 1 and summary.skipped == 1 and summary.finished
    assert summary.interventions == 0  # 略過的反應不期待畫面一定改變


def test_max_steps():
    n = {"i": 0}

    def observe():
        n["i"] += 1
        return snap(PHASE_MY_TURN, n["i"])

    summary = make(observe, lambda s: result(), max_steps=5)[0].run()
    assert summary.reason == "max_steps" and summary.steps == 5


def test_stopped_controller_ends_run():
    runner, controller = make(seq([snap(PHASE_MY_TURN, "a")]), lambda s: result())
    controller.stop()
    assert runner.run().reason == "stopped"


def test_jsonl_has_game_finished(tmp_path):
    ids = EventIds(prefix="r")
    with AppLogger(log_dir=str(tmp_path), game_id="g_log") as logger:
        observe = seq([snap(PHASE_MY_TURN, "a"), snap(PHASE_WAITING), snap(PHASE_OVER)])
        make(observe, lambda s: result(), logger=logger, ids=ids)[0].run()

    events = [json.loads(l) for l in (tmp_path / "g_log.jsonl").read_text(encoding="utf-8").splitlines()]
    types = [e["event_type"] for e in events]

    assert types[-1] == "game_finished"
    assert "game_step" in [e["payload"].get("kind") for e in events]
    assert events[-1]["payload"]["summary"]["finished"] is True


if __name__ == "__main__":
    run_module(globals(), "test_game_runner")