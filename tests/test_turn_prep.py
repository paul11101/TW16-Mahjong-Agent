"""W7 整理：回合前準備（重拍、記錄、不一致就暫停）的測試，合成畫面，不需要瀏覽器。

執行方式（專案根目錄）：
    python -m tests.test_turn_prep
或
    python -m pytest tests/test_turn_prep.py -v
"""

import json

import numpy as np

from src.common.logger import AppLogger
from src.control.controller import AgentController
from src.control.errors import ERR_CAPTURE_FAILED, ERR_LOW_CONFIDENCE, ERR_STATE_MISMATCH
from src.control.pipeline import EventIds
from src.control.state_guard import StateGuard
from src.control.tile_mapper import TileBox, TileMapper
from src.control.turn_prep import prepare_turn
from test_interface.fakes import FakeMouse
from tests._runner import run_module

HAND = [0, 1, 2, 3, 4, 5, 9, 10, 11, 18, 19, 20, 27, 27, 31, 31, 33]
FRAME = np.zeros((1200, 1920, 3), dtype=np.uint8)


def boxes_for(hand, low_index=None):
    return [
        TileBox(tile, 100 + i * 30, 600, 26, 40, confidence=0.3 if i == low_index else 0.95)
        for i, tile in enumerate(sorted(hand))
    ]


def _setup(logger=None):
    controller = AgentController(game_id="t", mouse=FakeMouse())
    controller.start()
    ids = EventIds(prefix="p")
    guard = StateGuard(controller, game_id="t", next_event_id=ids.next, logger=logger)
    return controller, guard, ids, TileMapper()


def _prep(controller, guard, ids, mapper, capture, boxes_fn, logger=None, **kw):
    return prepare_turn(
        controller, guard, mapper, capture, boxes_fn, HAND,
        game_id="t", next_event_id=ids.next, logger=logger, sleep=lambda s: None, **kw,
    )


def test_ok_updates_mapper_and_keeps_running():
    controller, guard, ids, mapper = _setup()
    prep = _prep(controller, guard, ids, mapper, lambda: FRAME, lambda f: boxes_for(HAND))

    assert prep.ok and prep.failure is None and prep.refresh.ok
    assert mapper.tiles() == sorted(HAND)
    assert controller.is_running and guard.mismatch_count == 0


def test_mismatch_pauses_and_clears_mapper():
    controller, guard, ids, mapper = _setup()
    prep = _prep(controller, guard, ids, mapper, lambda: FRAME,
                 lambda f: boxes_for(HAND[:-2]), max_attempts=2)

    assert not prep.ok
    assert prep.failure.error == ERR_STATE_MISMATCH and prep.failure.legal_count == 0
    assert prep.refresh.attempts == 2
    assert controller.is_paused and guard.mismatch_count == 1
    assert mapper.tiles() == []  # 舊牌框不能留著


def test_low_confidence_pauses_without_state_mismatch():
    controller, guard, ids, mapper = _setup()
    prep = _prep(controller, guard, ids, mapper, lambda: FRAME,
                 lambda f: boxes_for(HAND, low_index=0), max_attempts=2)

    assert prep.failure.error == ERR_LOW_CONFIDENCE
    assert controller.is_paused and guard.mismatch_count == 0


def test_capture_failure_pauses():
    controller, guard, ids, mapper = _setup()
    prep = _prep(controller, guard, ids, mapper, lambda: None, lambda f: [])

    assert prep.failure.error == ERR_CAPTURE_FAILED
    assert controller.is_paused and guard.mismatch_count == 0


def test_failure_is_logged(tmp_path):
    with AppLogger(log_dir=str(tmp_path), game_id="t_prep") as logger:
        controller, guard, ids, mapper = _setup(logger)
        _prep(controller, guard, ids, mapper, lambda: FRAME,
              lambda f: boxes_for(HAND[:-2]), logger=logger, max_attempts=1,
              context={"phase": "my_turn"})

    events = [json.loads(l) for l in (tmp_path / "t_prep.jsonl").read_text(encoding="utf-8").splitlines()]
    types = [e["event_type"] for e in events]
    assert "warning" in types and "state_mismatch" in types
    mismatch = next(e for e in events if e["event_type"] == "state_mismatch")
    assert mismatch["payload"]["context"]["phase"] == "my_turn"
    assert mismatch["payload"]["context"]["error"] == ERR_STATE_MISMATCH


if __name__ == "__main__":
    run_module(globals(), "test_turn_prep")