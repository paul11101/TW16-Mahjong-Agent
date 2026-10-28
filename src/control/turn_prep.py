"""回合前準備：重拍手牌 -> 寫 JSONL -> 不一致就記錄並暫停（W7 整理，取代 run_full_game 內的 prepare）。

成功：failure 是 None，mapper 已更新。
失敗：controller 已暫停，failure 是可直接回給 GameRunner 的 TurnResult。
"""

from __future__ import annotations

import time
from typing import Any, Callable, Iterable, NamedTuple, Sequence

from src.common.logger import AppLogger
from src.control.controller import AgentController
from src.control.errors import ERR_STATE_MISMATCH
from src.control.pipeline import TurnResult
from src.control.refresh import RefreshResult, log_refresh_result, refresh_hand
from src.control.state_guard import StateGuard
from src.control.tile_mapper import TileBox


class PreparedTurn(NamedTuple):
    refresh: RefreshResult
    failure: TurnResult | None

    @property
    def ok(self) -> bool:
        return self.failure is None


def prepare_turn(
    controller: AgentController,
    guard: StateGuard,
    mapper: Any,
    capture_fn: Callable[[], Any],
    boxes_fn: Callable[[Any], Sequence[TileBox]],
    expected_hand: Iterable[int],
    *,
    game_id: str,
    next_event_id: Callable[[], str],
    logger: AppLogger | None = None,
    meld_count: int = 0,
    max_attempts: int = 3,
    retry_delay: float = 0.2,
    context: dict[str, Any] | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> PreparedTurn:
    expected = list(expected_hand)

    result = refresh_hand(
        capture_fn, boxes_fn, expected,
        mapper=mapper, meld_count=meld_count,
        max_attempts=max_attempts, retry_delay=retry_delay, sleep=sleep,
    )
    log_refresh_result(logger, game_id, next_event_id(), result)
    if result.ok:
        return PreparedTurn(result, None)

    # 牌對不上才算「狀態不一致」；低信心、擷取失敗只暫停，不記 state_mismatch
    if result.check is not None and not result.check.ok:
        guard.verify(
            [b.tile for b in result.boxes], expected, meld_count=meld_count,
            context={**(context or {}), "error": result.error},
        )
    controller.pause()  # 已經暫停時是 no-op

    return PreparedTurn(result, TurnResult(legal_count=0, error=result.error or ERR_STATE_MISMATCH))