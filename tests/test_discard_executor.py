"""W3 D4 出牌執行器測試（假滑鼠、合成牌框，不需要瀏覽器）。

執行方式（專案根目錄）：
    python -m tests.test_discard_executor
或
    python -m pytest tests/test_discard_executor.py -v
"""

import json
import tempfile
from pathlib import Path

from src.common.logger import AppLogger
from src.common.schemas import ActionType
from src.common.schemas import LegalAction as SchemaLegalAction
from src.control.capture import CaptureRegion
from src.control.controller import AgentController
from src.control.discard_executor import execute_discard
from src.control.tile_mapper import TileBox, TileMapper
from src.strategy.interfaces import Decision, LegalAction

REGION = CaptureRegion(100, 50, 1920, 1200)
HAND = [0, 1, 2, 27, 27]


class FakeMouse:
    def __init__(self) -> None:
        self.clicks: list[tuple[int, int]] = []

    def click(self, x: int, y: int) -> None:
        self.clicks.append((x, y))


class _Ids:
    def __init__(self) -> None:
        self.n = 0

    def next(self) -> str:
        self.n += 1
        return f"t_{self.n:04d}"


def _mapper(hand=HAND) -> TileMapper:
    mapper = TileMapper(frame_size=(1920, 1200))
    mapper.update([TileBox(t, 100 + i * 30, 600, 26, 40) for i, t in enumerate(sorted(hand))])
    return mapper


def _decision(action=ActionType.DISCARD, tile=0, action_id=None) -> Decision:
    return Decision(
        action=LegalAction(id=action_id or f"{ActionType(action).value}_{tile}", action=action, tile=tile),
        score=0.0,
        reason="test",
    )


def _schema(decision: Decision) -> SchemaLegalAction:
    return SchemaLegalAction(
        action_id=decision.action.id,
        action_type=decision.action.action,
        tile_ids=[decision.action.tile],
    )


def _run(decision, mapper, mouse, *, logger=None, foreground=None, start=True):
    controller = AgentController(game_id="t", mouse=mouse, logger=logger)
    if start:
        controller.start()
    ids = _Ids()
    return execute_discard(
        decision, mapper, REGION, controller,
        game_id="t", decision_id="decision_1", schema_action=_schema(decision),
        next_event_id=ids.next, logger=logger, parent_event_id="parent_1",
        foreground_check=foreground,
    )


def test_success_clicks_expected_point():
    mouse = FakeMouse()
    receipt, plan = _run(_decision(tile=0), _mapper(), mouse)

    # 牌 0：box (100,600,26,40) 中心 (113,620)，加視窗偏移 (100,50)
    assert mouse.clicks == [(213, 670)]
    assert plan.frame_point == (113, 620)
    assert receipt.success is True
    assert receipt.ui_action_executed is True
    assert receipt.state_verified is False
    assert receipt.error_code is None
    assert receipt.latency_ms is not None and receipt.latency_ms >= 0
    assert receipt.decision_id == "decision_1"


def test_tile_not_found_does_not_click():
    mouse = FakeMouse()
    receipt, plan = _run(_decision(tile=9), _mapper(), mouse)

    assert mouse.clicks == []
    assert plan is None
    assert receipt.success is False
    assert receipt.error_code == "TILE_NOT_FOUND"


def test_unsupported_action_does_not_click():
    mouse = FakeMouse()
    receipt, _ = _run(_decision(action=ActionType.WIN, tile=0), _mapper(), mouse)

    assert mouse.clicks == []
    assert receipt.error_code == "UNSUPPORTED_ACTION"


def test_not_foreground_blocks_click_and_requests_stop():
    mouse = FakeMouse()
    receipt, _ = _run(_decision(tile=0), _mapper(), mouse, foreground=lambda: False)

    assert mouse.clicks == []
    assert receipt.success is False
    assert receipt.error_code == "WINDOW_NOT_FOREGROUND"
    assert receipt.should_stop is True


def test_controller_not_running_blocks_click():
    mouse = FakeMouse()
    receipt, _ = _run(_decision(tile=0), _mapper(), mouse, start=False)

    assert mouse.clicks == []
    assert receipt.error_code == "CONTROLLER_NOT_RUNNING"


def test_jsonl_has_started_and_completed(tmp_path):
    with AppLogger(log_dir=str(tmp_path), game_id="t_log") as logger:
        _run(_decision(tile=0), _mapper(), FakeMouse(), logger=logger)

    lines = (tmp_path / "t_log.jsonl").read_text(encoding="utf-8").splitlines()
    events = [json.loads(line) for line in lines]
    types = [e["event_type"] for e in events]

    assert "action_started" in types
    assert "action_completed" in types
    completed = next(e for e in events if e["event_type"] == "action_completed")
    assert completed["payload"]["success"] is True
    assert completed["payload"]["state_verified"] is False
    assert completed["parent_event_id"] == next(
        e for e in events if e["event_type"] == "action_started"
    )["event_id"]


def test_jsonl_failure_is_action_failed(tmp_path):
    with AppLogger(log_dir=str(tmp_path), game_id="t_fail") as logger:
        _run(_decision(tile=9), _mapper(), FakeMouse(), logger=logger)

    types = [json.loads(l)["event_type"] for l in
             (tmp_path / "t_fail.jsonl").read_text(encoding="utf-8").splitlines()]
    assert "action_failed" in types
    assert "action_completed" not in types


if __name__ == "__main__":
    test_success_clicks_expected_point()
    test_tile_not_found_does_not_click()
    test_unsupported_action_does_not_click()
    test_not_foreground_blocks_click_and_requests_stop()
    test_controller_not_running_blocks_click()
    with tempfile.TemporaryDirectory() as d:
        test_jsonl_has_started_and_completed(Path(d) / "a")
        test_jsonl_failure_is_action_failed(Path(d) / "b")
    print("✅ test_discard_executor：7 項測試全部通過")