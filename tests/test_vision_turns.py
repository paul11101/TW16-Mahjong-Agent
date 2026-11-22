"""W8 真實遊戲回合函式測試：假 detector、假滑鼠、假時鐘，不需要視窗或 data/samples。

執行方式（專案根目錄）：
    python -m tests.test_vision_turns
或
    python -m pytest tests/test_vision_turns.py -v
"""

import numpy as np

from src.control.capture import CaptureRegion, ScreenCapture
from src.control.controller import AgentController
from src.control.game_runner import PHASE_MY_TURN, PHASE_REACTION, GameRunner, Snapshot
from src.control.pipeline import EventIds
from src.control.state_guard import StateGuard
from src.control.tile_mapper import TileMapper
from src.control.vision_adapter import DetectorVision, VisionObserver
from src.control.vision_turns import make_vision_turns
from test_interface.fakes import FakeMouse
from tests._runner import run_module
from tests.helpers import FakeClock

HAND = [0, 1, 2, 3, 4, 5, 9, 10, 11, 18, 19, 20, 27, 27, 31, 31, 33]  # 17 張，已排序
REGION = CaptureRegion(5, 7, 400, 100)
FRAME_SIZE = (400, 100)


def cards(tiles, *, low=()):
    return [
        {"name": str(t), "bbox": (10 + i * 20, 60, 15, 30), "confidence": 0.95,
         "margin": 0.2, "low_confidence": i in low}
        for i, t in enumerate(tiles)
    ]


def state(tiles, *, turn=True, over=False, low=()):
    return {"hand_cards": cards(tiles, low=low), "is_my_turn": turn, "is_animating": False,
            "in_settlement": over}


S17 = state(HAND)
S16 = state(HAND[:16], turn=False)
OVER = state([], turn=False, over=True)


class SeqDetector:
    """依序回傳 states，用完後一直回傳最後一個。"""

    base_height = 100.0

    def __init__(self, states):
        self.states, self.calls = list(states), 0

    def detect_full_state(self, image, scan_secondary_rois=False):
        i = min(self.calls, len(self.states) - 1)
        self.calls += 1
        return self.states[i]


def build(states, **kw):
    detector = SeqDetector(states)
    vision = DetectorVision(detector)
    mouse = FakeMouse()
    capturer = ScreenCapture(grab_fn=lambda r: np.zeros((100, 400, 4), dtype=np.uint8))
    controller = AgentController(game_id="g", mouse=mouse, capturer=capturer)
    controller.start()
    ids = EventIds()
    mapper = TileMapper(frame_size=FRAME_SIZE)
    guard = StateGuard(controller, game_id="g", next_event_id=ids.next)
    clock = FakeClock()
    turns = make_vision_turns(
        controller, vision, mapper, guard, REGION,
        game_id="g", ids=ids, sleep=lambda s: None, refresh_attempts=kw.pop("refresh_attempts", 1), **kw,
    )
    runner = GameRunner(
        controller, game_id="g", observe_fn=VisionObserver(controller.capture, vision).snapshot,
        turn_fns=turns, poll_interval=0.2, advance_timeout=5.0, idle_timeout=None,
        pause_timeout=1.0, clock=clock, sleep=clock.sleep,
    )
    return runner, mouse, detector, turns


def _expected_click(runner):
    tile = int(runner.records[0].action_id.split("_")[1])
    i = HAND.index(tile)  # 相同牌取最左邊那張
    return (10 + i * 20 + 7 + REGION.left, 60 + 15 + REGION.top)


def test_confirmed_discard_then_waiting_then_over():
    runner, mouse, detector, _ = build([S17, S17, S16, OVER])
    summary = runner.run()

    assert summary.finished and summary.unattended
    assert summary.steps == 1 and summary.completed == 1 and summary.failed == 0
    assert detector.calls == 4  # 第一次觀察 + 重拍確認 + 等待 + 結算
    assert mouse.clicks == [_expected_click(runner)]


def test_unconfirmed_discard_uses_one_detection():
    runner, mouse, detector, _ = build([S17, S16, OVER], confirm=False)
    summary = runner.run()

    assert summary.finished and summary.unattended and summary.completed == 1
    assert detector.calls == 3  # 少一次重拍
    assert mouse.clicks == [_expected_click(runner)]


def test_confirm_mismatch_pauses_without_click():
    changed = state(HAND[:-1] + [7])  # 重拍時讀到不同的手牌
    runner, mouse, _, _ = build([S17, changed])
    summary = runner.run()

    assert mouse.clicks == []
    assert summary.interventions == 1 and not summary.finished
    assert summary.error_codes == {"STATE_MISMATCH": 1}


def test_low_confidence_without_confirm_pauses():
    runner, mouse, _, _ = build([state(HAND, low={3})], confirm=False)
    summary = runner.run()

    assert mouse.clicks == []
    assert summary.interventions == 1
    assert summary.error_codes == {"LOW_CONFIDENCE": 1}


def test_low_confidence_with_confirm_pauses():
    runner, mouse, _, _ = build([state(HAND, low={3})], refresh_attempts=2)
    summary = runner.run()

    assert mouse.clicks == []
    assert summary.error_codes == {"LOW_CONFIDENCE": 1}


def test_reaction_turn_is_skipped_without_click():
    _, mouse, _, turns = build([S17])
    result = turns[PHASE_REACTION](Snapshot(phase="reaction"))

    assert result.skipped is True and result.receipt is None
    assert mouse.clicks == []
    assert PHASE_MY_TURN in turns


if __name__ == "__main__":
    run_module(globals(), "test_vision_turns")