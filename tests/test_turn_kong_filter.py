"""自己回合的暗槓目前沒有點擊映射：整合端只提供出牌，策略不會選到槓。

執行方式（專案根目錄）：
    python -m tests.test_turn_kong_filter
或
    python -m pytest tests/test_turn_kong_filter.py -v
"""

from src.common.schemas import ActionType
from src.control.capture import CaptureRegion
from src.control.controller import AgentController
from src.control.game_profile import state_from_visible_hand
from src.control.pipeline import EventIds, run_discard_turn
from src.strategy.action_policy import ActionPolicy
from test_interface.agent_runner import SEAT
from test_interface.fakes import FakeMouse
from tests._runner import run_module
from tests.helpers import make_hand_mapper

REGION = CaptureRegion(100, 50, 1920, 1200)
# 手上有四張 4：規則會提供暗槓
KONG_HAND = [4, 4, 4, 4, 0, 1, 2, 9, 10, 11, 18, 19, 20, 27, 27, 31, 33]


def test_own_turn_kong_is_filtered_out():
    state = state_from_visible_hand("t", KONG_HAND)
    mouse = FakeMouse()
    controller = AgentController(game_id="t", mouse=mouse)
    controller.start()
    try:
        result = run_discard_turn(
            state, SEAT, make_hand_mapper(KONG_HAND), REGION, controller,
            game_id="t", ids=EventIds(), policy=ActionPolicy(),
        )
    finally:
        controller.stop()

    assert result.legal_count == 13  # 13 種牌各一個出牌動作，沒有槓
    assert result.decision.action.action == ActionType.DISCARD
    assert result.success is True and len(mouse.clicks) == 1
    assert result.error is None


if __name__ == "__main__":
    run_module(globals(), "test_turn_kong_filter")