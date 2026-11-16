"""整合端反應動作轉接：優先用 GameState.get_reaction_actions，沒有才退回舊版。

執行方式（專案根目錄）：
    python -m tests.test_reaction_adapter
或
    python -m pytest tests/test_reaction_adapter.py -v
"""

from types import SimpleNamespace

import pytest

from src.common.schemas import ActionType
from src.control.pipeline import get_reaction_rules_actions
from src.rules.game_state import GameState, LastDiscard, PlayerState
from tests._runner import run_module

SEAT = 0
WIN_HAND = [0, 1, 2, 3, 3, 4, 5, 6, 9, 10, 11, 18, 19, 20, 27, 27]  # 上家打 3 可胡


def _state(hand=WIN_HAND, target=3):
    return GameState(
        game_id="t", current_turn=SEAT, wall_count=80,
        last_discard=LastDiscard(player_id=3, tile_id=target),
        players={i: PlayerState(seat_id=i, hand=list(hand) if i == SEAT else []) for i in range(4)},
    )


def _kinds(actions):
    return {ActionType(a.action_type) for a in actions}


def test_uses_rules_module_method():
    state = _state()
    assert get_reaction_rules_actions(state, SEAT) == state.get_reaction_actions(SEAT)
    assert ActionType.WIN in _kinds(get_reaction_rules_actions(state, SEAT))


def test_passed_win_is_respected_now():
    state = _state()
    state.players[SEAT].passed_win = True

    kinds = _kinds(get_reaction_rules_actions(state, SEAT))
    assert ActionType.WIN not in kinds and ActionType.PASS in kinds


def test_no_target_raises_value_error():
    state = _state()
    state.last_discard = None
    with pytest.raises(ValueError):
        get_reaction_rules_actions(state, SEAT)


def test_falls_back_when_state_has_no_method():
    fake = SimpleNamespace(
        last_discard=LastDiscard(player_id=3, tile_id=3),
        players={SEAT: SimpleNamespace(hand=list(WIN_HAND), melds=[])},
    )
    kinds = _kinds(get_reaction_rules_actions(fake, SEAT))
    assert {ActionType.WIN, ActionType.PASS} <= kinds

    fake.last_discard = None
    with pytest.raises(ValueError):
        get_reaction_rules_actions(fake, SEAT)


if __name__ == "__main__":
    run_module(globals(), "test_reaction_adapter")