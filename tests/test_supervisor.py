"""W5 D1/D5 監督者測試：暫停、繼續、中途停止與從 checkpoint 恢復（假滑鼠、假 sleep）。

執行方式（專案根目錄）：
    python -m tests.test_supervisor
或
    python -m pytest tests/test_supervisor.py -v
"""

import json

import pytest

from src.common.logger import AppLogger
from src.common.schemas import ActionReceipt
from src.control.controller import AgentController
from src.control.errors import ERR_CONTROLLER_NOT_RUNNING, ERR_STATE_MISMATCH
from src.control.pipeline import EventIds, TurnResult
from src.control.supervisor import (
    RunSupervisor,
    load_checkpoint,
    save_checkpoint,
    start_index_from_checkpoint,
)
from test_interface.fakes import FakeMouse
from tests._runner import run_module


def receipt(success=True, should_stop=False, error=None):
    return ActionReceipt(
        receipt_id="r", game_id="t", event_id="e", decision_id="d",
        success=success, ui_action_executed=True, should_stop=should_stop, error_code=error,
    )


def ok_turn():
    return TurnResult(legal_count=1, receipt=receipt())


def fail_turn(*, should_stop=False, error="ACTION_TIMEOUT"):
    return TurnResult(
        legal_count=1, receipt=receipt(False, should_stop, error), error=error
    )


def make_controller():
    controller = AgentController(game_id="t", mouse=FakeMouse())
    controller.start()
    return controller


def auto_resume_sleep(controller, sleeps):
    """假 sleep：有人在等的時候，模擬「使用者按了繼續」。"""

    def sleep(seconds):
        sleeps.append(seconds)
        if controller.is_paused:
            controller.resume()

    return sleep


def test_all_turns_complete_and_checkpoint_finished(tmp_path):
    controller = make_controller()
    path = tmp_path / "t.checkpoint.json"
    sup = RunSupervisor(controller, game_id="t", checkpoint_path=path, sleep=lambda s: None)

    summary = sup.run([ok_turn, ok_turn, ok_turn])

    assert summary.finished and summary.completed == 3 and summary.failed == 0
    assert summary.next_turn == 3 and summary.reason == "finished"
    checkpoint = load_checkpoint(path)
    assert checkpoint.next_turn == 3 and checkpoint.reason == "finished"
    assert start_index_from_checkpoint(path) == 0  # 跑完了，下次從頭開始


def test_skipped_turn_is_counted_and_advances():
    controller = make_controller()
    sup = RunSupervisor(controller, game_id="t", sleep=lambda s: None)

    summary = sup.run([ok_turn, lambda: TurnResult(legal_count=1, skipped=True), ok_turn])

    assert summary.completed == 2 and summary.skipped == 1 and summary.finished


def test_pause_mid_run_waits_then_resumes():
    controller = make_controller()
    sleeps, calls = [], []

    def turn(i, pause=False):
        def run():
            calls.append(i)
            if pause:
                controller.pause()  # 回合做完時使用者按了暫停
            return ok_turn()

        return run

    sup = RunSupervisor(controller, game_id="t", poll_interval=0.1,
                        sleep=auto_resume_sleep(controller, sleeps))
    summary = sup.run([turn(0), turn(1, pause=True), turn(2)])

    assert calls == [0, 1, 2]
    assert summary.finished and summary.completed == 3
    assert sleeps == [0.1]  # 暫停期間只等了一輪就被繼續


def test_stop_mid_run_then_resume_from_checkpoint(tmp_path):
    path = tmp_path / "t.checkpoint.json"
    calls = []

    def make_turns(controller):
        def turn(i, stop=False):
            def run():
                calls.append(i)
                if stop:
                    controller.stop()  # 第 2 個回合結束時按了停止
                return ok_turn()

            return run

        return [turn(0), turn(1, stop=True), turn(2), turn(3)]

    # 第一次執行：做到一半被停止
    first = make_controller()
    summary = RunSupervisor(first, game_id="t", checkpoint_path=path, sleep=lambda s: None).run(
        make_turns(first)
    )
    assert summary.stopped and summary.reason == "stopped"
    assert summary.completed == 2 and summary.next_turn == 2
    assert calls == [0, 1]
    assert load_checkpoint(path).next_turn == 2

    # 恢復：STOPPED 的 controller 不能重啟，所以建新的，從 checkpoint 接著跑
    second = make_controller()
    summary = RunSupervisor(second, game_id="t", checkpoint_path=path, sleep=lambda s: None).run(
        make_turns(second), start_at=start_index_from_checkpoint(path)
    )
    assert summary.finished and summary.completed == 2
    assert calls == [0, 1, 2, 3]  # 沒有重跑 0、1
    assert load_checkpoint(path).reason == "finished"


def test_stop_during_failed_turn_does_not_advance(tmp_path):
    controller = make_controller()
    path = tmp_path / "t.checkpoint.json"

    def interrupted():
        controller.stop()
        return fail_turn(error=ERR_CONTROLLER_NOT_RUNNING)

    summary = RunSupervisor(controller, game_id="t", checkpoint_path=path, sleep=lambda s: None).run(
        [ok_turn, interrupted, ok_turn]
    )

    assert summary.stopped and summary.completed == 1 and summary.failed == 1
    assert summary.next_turn == 1  # 被中斷的回合還沒完成，恢復時要重跑
    assert load_checkpoint(path).next_turn == 1


def test_should_stop_failure_pauses_and_reruns_same_turn():
    controller = make_controller()
    sleeps, calls = [], []

    def flaky():
        calls.append("flaky")
        return fail_turn(should_stop=True, error="WINDOW_NOT_FOREGROUND") if calls.count("flaky") == 1 else ok_turn()

    summary = RunSupervisor(
        controller, game_id="t", sleep=auto_resume_sleep(controller, sleeps)
    ).run([ok_turn, flaky, ok_turn])

    assert calls == ["flaky", "flaky"]
    assert summary.finished and summary.completed == 3 and summary.failed == 1  # 失敗不從分母刪除
    assert len(sleeps) == 1


def test_state_mismatch_without_receipt_pauses_and_reruns():
    controller = make_controller()
    calls = []

    def guarded():
        calls.append(1)
        if len(calls) == 1:
            return TurnResult(legal_count=0, error=ERR_STATE_MISMATCH)
        return ok_turn()

    summary = RunSupervisor(
        controller, game_id="t", sleep=auto_resume_sleep(controller, [])
    ).run([guarded])

    assert len(calls) == 2 and summary.finished and summary.completed == 1 and summary.failed == 1


def test_max_turn_attempts_stops_controller(tmp_path):
    controller = make_controller()
    path = tmp_path / "t.checkpoint.json"
    calls = []

    def always_bad():
        calls.append(1)
        return TurnResult(legal_count=0, error=ERR_STATE_MISMATCH)

    summary = RunSupervisor(
        controller, game_id="t", checkpoint_path=path, max_turn_attempts=2,
        sleep=auto_resume_sleep(controller, []),
    ).run([always_bad, ok_turn])

    assert len(calls) == 2
    assert summary.stopped and summary.reason == "max_attempts" and summary.failed == 2
    assert controller.is_stopped
    assert load_checkpoint(path).next_turn == 0


def test_pause_timeout_stops():
    controller = make_controller()
    controller.pause()
    sleeps = []

    summary = RunSupervisor(
        controller, game_id="t", poll_interval=0.1, pause_timeout=0.25, sleep=sleeps.append
    ).run([ok_turn])

    assert summary.reason == "pause_timeout" and summary.completed == 0
    assert controller.is_stopped
    assert len(sleeps) == 3


def test_not_started_controller_does_not_run():
    controller = AgentController(game_id="t", mouse=FakeMouse())  # 沒有 start()
    summary = RunSupervisor(controller, game_id="t", sleep=lambda s: None).run([ok_turn])

    assert summary.reason == "not_started" and summary.completed == 0


def test_checkpoint_roundtrip_and_missing_file(tmp_path):
    path = tmp_path / "sub" / "x.checkpoint.json"
    assert load_checkpoint(path) is None
    assert start_index_from_checkpoint(path) == 0

    save_checkpoint(path, "g1", 4, "stopped")
    loaded = load_checkpoint(path)
    assert (loaded.game_id, loaded.next_turn, loaded.reason) == ("g1", 4, "stopped")
    assert start_index_from_checkpoint(path) == 4


def test_supervisor_logs_retry_event(tmp_path):
    controller = make_controller()
    ids = EventIds(prefix="s")
    calls = []

    def flaky():
        calls.append(1)
        return TurnResult(legal_count=0, error=ERR_STATE_MISMATCH) if len(calls) == 1 else ok_turn()

    with AppLogger(log_dir=str(tmp_path), game_id="t_sup") as logger:
        RunSupervisor(
            controller, game_id="t_sup", logger=logger, next_event_id=ids.next,
            sleep=auto_resume_sleep(controller, []),
        ).run([flaky])

    events = [json.loads(l) for l in (tmp_path / "t_sup.jsonl").read_text(encoding="utf-8").splitlines()]
    info = [e for e in events if e["event_type"] == "system_info"]
    assert info and info[0]["payload"]["kind"] == "turn_paused_for_retry"
    assert info[0]["payload"]["error"] == ERR_STATE_MISMATCH


def test_max_turn_attempts_must_be_positive():
    with pytest.raises(ValueError):
        RunSupervisor(make_controller(), game_id="t", max_turn_attempts=0)


if __name__ == "__main__":
    run_module(globals(), "test_supervisor")