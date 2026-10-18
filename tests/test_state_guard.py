"""W5 D2 狀態一致性檢查與暫停測試（假滑鼠，不需要瀏覽器）。

執行方式（專案根目錄）：
    python -m tests.test_state_guard
或
    python -m pytest tests/test_state_guard.py -v
"""

import json

from src.common.logger import AppLogger
from src.control.controller import AgentController, ControlState
from src.control.pipeline import EventIds
from src.control.state_guard import StateGuard, check_state, valid_hand_sizes
from test_interface.fakes import FakeMouse
from tests._runner import run_module
from tests.helpers import make_hand_mapper

HAND = [0, 1, 2, 3, 4, 5, 9, 10, 11, 18, 19, 20, 27, 27, 31, 31, 33]  # 17 張


def test_valid_hand_sizes():
    assert valid_hand_sizes(0) == (16, 17)
    assert valid_hand_sizes(1) == (13, 14)
    assert valid_hand_sizes(5) == (1, 2)


def test_matching_hand_is_ok():
    check = check_state(HAND, HAND)
    assert check.ok and check.problems == () and check.missing == () and check.extra == ()


def test_order_does_not_matter():
    assert check_state(list(reversed(HAND)), HAND).ok


def test_missing_and_extra():
    visible = [t for t in HAND if t != 33] + [7]  # 少 33、多 7，張數仍是 17
    check = check_state(visible, HAND)

    assert not check.ok
    assert check.missing == (33,) and check.extra == (7,)


def test_wrong_size_is_reported():
    check = check_state(HAND[:-2], HAND)

    assert not check.ok
    assert any("畫面手牌 15 張" in p for p in check.problems)
    assert check.missing == (31, 33)


def test_meld_count_changes_valid_size():
    hand13 = HAND[:13]

    assert check_state(hand13, hand13, meld_count=1).ok
    assert not check_state(hand13, hand13, meld_count=0).ok


def test_flower_in_hand_area_and_five_copies():
    flower = check_state(HAND[:-1] + [34], HAND[:-1] + [34])
    assert any("花牌" in p for p in flower.problems)

    five = check_state([27] * 5 + HAND[:11], [27] * 5 + HAND[:11])
    assert any("超過 4 張" in p for p in five.problems)


def _guard(tmp_path, game_id):
    logger = AppLogger(log_dir=str(tmp_path), game_id=game_id)
    mouse = FakeMouse()
    controller = AgentController(game_id=game_id, mouse=mouse, logger=logger)
    controller.start()
    ids = EventIds(prefix="g")
    return StateGuard(controller, game_id=game_id, next_event_id=ids.next, logger=logger), controller, mouse, logger


def test_ok_does_not_pause(tmp_path):
    guard, controller, mouse, logger = _guard(tmp_path, "t_ok")
    try:
        assert guard.verify(HAND, HAND).ok
        assert controller.state == ControlState.RUNNING
        assert guard.mismatch_count == 0
        assert controller.click(1, 2) is True
    finally:
        controller.stop()
        logger.close()


def test_mismatch_pauses_logs_and_blocks_click(tmp_path):
    guard, controller, mouse, logger = _guard(tmp_path, "t_bad")
    try:
        check = guard.verify(HAND[:-2], HAND, context={"turn": 3})

        assert not check.ok
        assert guard.mismatch_count == 1
        assert controller.state == ControlState.PAUSED
        assert controller.click(1, 2) is False  # 暫停後不能點
        assert mouse.clicks == []
    finally:
        controller.stop()
        logger.close()

    events = [json.loads(l) for l in (tmp_path / "t_bad.jsonl").read_text(encoding="utf-8").splitlines()]
    types = [e["event_type"] for e in events]
    assert types.index("state_mismatch") < types.index("game_paused")

    mismatch = next(e for e in events if e["event_type"] == "state_mismatch")
    assert mismatch["payload"]["missing"] == [31, 33]
    assert mismatch["payload"]["context"] == {"turn": 3}


def test_verify_mapper_uses_box_tiles(tmp_path):
    guard, controller, _mouse, logger = _guard(tmp_path, "t_map")
    try:
        assert guard.verify_mapper(make_hand_mapper(HAND), HAND).ok
        assert not guard.verify_mapper(make_hand_mapper(HAND[:-2]), HAND).ok
        assert controller.is_paused
    finally:
        controller.stop()
        logger.close()


def test_pause_on_mismatch_can_be_disabled(tmp_path):
    guard, controller, _mouse, logger = _guard(tmp_path, "t_nopause")
    try:
        guard.pause_on_mismatch = False
        assert not guard.verify(HAND[:-2], HAND).ok
        assert controller.is_running
    finally:
        controller.stop()
        logger.close()


if __name__ == "__main__":
    run_module(globals(), "test_state_guard")