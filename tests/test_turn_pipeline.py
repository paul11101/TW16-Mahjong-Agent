"""W3 D5 整回合管線測試：假牌局 -> 決策 -> 假滑鼠點擊 -> 回執 -> JSONL 順序。

執行方式（專案根目錄）：
    python -m tests.test_turn_pipeline
或
    python -m pytest tests/test_turn_pipeline.py -v
"""

import json
import tempfile
from pathlib import Path

from src.common.logger import AppLogger
from src.control.capture import CaptureRegion
from src.control.controller import AgentController
from src.control.pipeline import EventIds, run_discard_turn
from src.control.tile_mapper import TileBox, TileMapper
from src.rules.game_state import GameState, PlayerState
from test_interface.agent_runner import SEAT, make_fake_game_state

REGION = CaptureRegion(100, 50, 1920, 1200)


class FakeMouse:
    def __init__(self) -> None:
        self.clicks: list[tuple[int, int]] = []

    def click(self, x: int, y: int) -> None:
        self.clicks.append((x, y))


def _mapper(hand) -> TileMapper:
    mapper = TileMapper(frame_size=(1920, 1200))
    mapper.update([TileBox(t, 100 + i * 30, 600, 26, 40) for i, t in enumerate(sorted(hand))])
    return mapper


def _run(state, mapper, log_dir, game_id, mouse, foreground=None):
    with AppLogger(log_dir=str(log_dir), game_id=game_id) as logger:
        controller = AgentController(game_id=game_id, mouse=mouse, logger=logger)
        controller.start()
        try:
            return run_discard_turn(
                state, SEAT, mapper, REGION, controller,
                game_id=game_id, ids=EventIds(), logger=logger,
                foreground_check=foreground,
            )
        finally:
            controller.stop()


def _types(log_dir, game_id):
    lines = (Path(log_dir) / f"{game_id}.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(line)["event_type"] for line in lines]


def test_full_turn_success(tmp_path):
    state = make_fake_game_state("t_ok")
    mouse = FakeMouse()
    result = _run(state, _mapper(state.players[SEAT].hand), tmp_path, "t_ok", mouse)

    assert result.success is True
    assert result.decision.action.id == "discard_0"
    assert mouse.clicks == [(213, 670)]  # 牌 0 中心 (113,620) + 視窗偏移 (100,50)
    assert result.receipt.state_verified is False
    assert _types(tmp_path, "t_ok") == [
        "game_started",
        "state_updated",
        "legal_actions_generated",
        "decision_made",
        "action_started",
        "action_completed",
        "game_stopped",
    ]


def test_missing_tile_logs_failure_without_click(tmp_path):
    state = make_fake_game_state("t_miss")
    mouse = FakeMouse()
    result = _run(state, _mapper([5, 6, 7]), tmp_path, "t_miss", mouse)

    assert result.success is False
    assert result.error == "TILE_NOT_FOUND"
    assert mouse.clicks == []
    types = _types(tmp_path, "t_miss")
    assert "action_failed" in types and "action_completed" not in types


def test_not_foreground_requests_stop(tmp_path):
    state = make_fake_game_state("t_bg")
    mouse = FakeMouse()
    result = _run(state, _mapper(state.players[SEAT].hand), tmp_path, "t_bg", mouse,
                  foreground=lambda: False)

    assert mouse.clicks == []
    assert result.error == "WINDOW_NOT_FOREGROUND"
    assert result.receipt.should_stop is True


def test_no_legal_actions(tmp_path):
    state = GameState(
        game_id="t_none",
        players={i: PlayerState(seat_id=i) for i in range(4)},  # 手牌全空 -> 沒有合法動作
    )
    mouse = FakeMouse()
    result = _run(state, _mapper([]), tmp_path, "t_none", mouse)

    assert result.legal_count == 0
    assert result.receipt is None
    assert result.error == "NO_LEGAL_ACTIONS"
    assert mouse.clicks == []


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as d:
        base = Path(d)
        test_full_turn_success(base / "a")
        test_missing_tile_logs_failure_without_click(base / "b")
        test_not_foreground_requests_stop(base / "c")
        test_no_legal_actions(base / "d")
    print("✅ test_turn_pipeline：4 項測試全部通過")