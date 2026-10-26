"""莊家輪替、連莊與圈風更新。"""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .game_state import GameState


class DealerManager:
    """依本局胡牌者或流局結果更新莊家與圈風。"""

    @staticmethod
    def advance(
        state: GameState,
        winner_seats: Iterable[int] = (),
        *,
        is_draw: bool = False,
    ) -> None:
        winners = list(winner_seats)
        if any(
            not isinstance(seat, int)
            or isinstance(seat, bool)
            or seat not in range(4)
            for seat in winners
        ):
            raise ValueError("Winner seats must be between 0 and 3")
        if not isinstance(is_draw, bool):
            raise ValueError("is_draw must be a boolean")
        if is_draw != (not winners):
            raise ValueError("A drawn round must have no winners; a win must have at least one")
        if state.dealer not in range(4):
            raise ValueError("Dealer seat must be between 0 and 3")
        if state.round_wind not in range(4):
            raise ValueError("Round wind must be between 0 and 3")
        if state.lian_zhuang < 0:
            raise ValueError("Consecutive dealer count cannot be negative")

        if is_draw or state.dealer in winners:
            state.lian_zhuang += 1
            return

        previous_dealer = state.dealer
        state.dealer = (previous_dealer + 1) % 4
        state.lian_zhuang = 0
        if previous_dealer == 3:
            state.round_wind = (state.round_wind + 1) % 4
