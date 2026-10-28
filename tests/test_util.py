"""W7 整理：util、event_log 的測試。

執行方式（專案根目錄）：
    python -m tests.test_util
或
    python -m pytest tests/test_util.py -v
"""

import json

from src.common.logger import AppLogger
from src.control.controller import AgentController
from src.control.event_log import log_info
from src.control.pipeline import EventIds
from src.control.util import atomic_write_json, p95, wait_until_running
from test_interface.fakes import FakeMouse
from tests._runner import run_module


def _controller(state):
    controller = AgentController(game_id="t", mouse=FakeMouse())
    if state != "idle":
        controller.start()
    if state == "paused":
        controller.pause()
    if state == "stopped":
        controller.stop()
    return controller


def test_p95():
    assert p95([float(i) for i in range(1, 101)]) == 95.0
    assert p95([7.0]) == 7.0
    assert p95([]) is None


def test_atomic_write_json(tmp_path):
    path = tmp_path / "a" / "x.json"
    atomic_write_json(path, {"k": "中文"})
    assert json.loads(path.read_text(encoding="utf-8")) == {"k": "中文"}
    assert not (tmp_path / "a" / "x.json.tmp").exists()

    atomic_write_json(path, {"k": 2})
    assert json.loads(path.read_text(encoding="utf-8")) == {"k": 2}


def test_wait_until_running_states():
    assert wait_until_running(_controller("running"), poll_interval=0.1) is None
    assert wait_until_running(_controller("stopped"), poll_interval=0.1) == "stopped"
    assert wait_until_running(_controller("idle"), poll_interval=0.1) == "not_started"


def test_wait_until_running_resumes():
    controller = _controller("paused")
    sleeps = []

    def sleep(seconds):
        sleeps.append(seconds)
        controller.resume()

    assert wait_until_running(controller, poll_interval=0.1, sleep=sleep) is None
    assert sleeps == [0.1]


def test_wait_until_running_pause_timeout_stops():
    controller = _controller("paused")
    sleeps = []

    reason = wait_until_running(controller, poll_interval=0.1, pause_timeout=0.25, sleep=sleeps.append)

    assert reason == "pause_timeout" and controller.is_stopped
    assert len(sleeps) == 3


def test_log_info(tmp_path):
    ids = EventIds(prefix="e")
    with AppLogger(log_dir=str(tmp_path), game_id="t_log") as logger:
        log_info(logger, ids.next, "t_log", "hello", console_message="hi", n=1)
        log_info(None, ids.next, "t_log", "ignored")  # 沒有 logger：不寫、不消耗 id

    events = [json.loads(l) for l in (tmp_path / "t_log.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(events) == 1
    assert events[0]["event_type"] == "system_info" and events[0]["event_id"] == "e_0001"
    assert events[0]["payload"] == {"kind": "hello", "n": 1}
    assert ids.next() == "e_0002"


if __name__ == "__main__":
    run_module(globals(), "test_util")