"""重新擷取流程與狀態重建入口（W5 D3、D4 低信心處理）。

refresh_hand()：
    擷取 -> 取得牌框 -> 低信心就重拍 -> 與規則狀態比對 -> 不一致就重拍 -> 最多 max_attempts 次。
    成功：更新 TileMapper（只放高信心牌框）。
    失敗：清空 TileMapper（舊牌框已過期，寧可 TILE_NOT_FOUND 也不要點到舊位置），
          回傳 error（LOW_CONFIDENCE / STATE_MISMATCH / CAPTURE_FAILED）。

rebuild_own_hand()：狀態重建入口。
    以「畫面上確認的手牌」覆寫規則狀態裡自己的手牌，回傳新的 GameState（不改原物件）與差異。
    目前只能重建自己的手牌；河牌／副露／花牌／分數要等視覺能辨識後再接進來。

兩者都不點擊、不決策。boxes_fn 由呼叫端提供（測試介面用 DOM、真實遊戲用視覺 Observation）。
"""

from __future__ import annotations

import time
from collections import Counter
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Sequence

from src.common.events import EventSource, EventType, create_event
from src.common.logger import AppLogger
from src.control.errors import ERR_CAPTURE_FAILED, ERR_LOW_CONFIDENCE, ERR_STATE_MISMATCH
from src.control.state_guard import StateCheck, check_state
from src.control.tile_mapper import TileBox


@dataclass(frozen=True)
class RefreshResult:
    ok: bool
    boxes: tuple[TileBox, ...]  # 成功時是全部高信心牌框；失敗時是最後一次的高信心牌框
    attempts: int
    error: str | None = None
    low_confidence: tuple[TileBox, ...] = ()
    check: StateCheck | None = None
    attempt_log: tuple[dict[str, Any], ...] = ()


def refresh_hand(
    capture_fn: Callable[[], Any],
    boxes_fn: Callable[[Any], Sequence[TileBox]],
    expected_hand: Iterable[int],
    *,
    mapper: Any | None = None,
    meld_count: int = 0,
    min_confidence: float = 0.6,
    max_attempts: int = 3,
    retry_delay: float = 0.2,
    sleep: Callable[[float], None] = time.sleep,
) -> RefreshResult:
    """重新擷取手牌直到「全是高信心」且「與規則狀態一致」，或用完次數。"""
    if max_attempts < 1:
        raise ValueError("max_attempts 至少為 1")

    expected = list(expected_hand)
    log: list[dict[str, Any]] = []
    error = ERR_STATE_MISMATCH
    last_boxes: tuple[TileBox, ...] = ()
    last_low: tuple[TileBox, ...] = ()
    last_check: StateCheck | None = None

    for attempt in range(1, max_attempts + 1):
        frame = capture_fn()
        if frame is None:
            log.append({"attempt": attempt, "result": "capture_failed"})
            _clear(mapper)
            return RefreshResult(False, (), attempt, ERR_CAPTURE_FAILED, attempt_log=tuple(log))

        boxes = tuple(boxes_fn(frame))
        low = tuple(b for b in boxes if b.confidence < min_confidence)
        good = tuple(b for b in boxes if b.confidence >= min_confidence)
        last_boxes = good

        if low:
            error = ERR_LOW_CONFIDENCE
            last_low = low
            log.append({
                "attempt": attempt,
                "result": "low_confidence",
                "count": len(low),
                "min_confidence": round(min(b.confidence for b in low), 4),
            })
        else:
            last_low = ()
            check = check_state([b.tile for b in good], expected, meld_count=meld_count)
            last_check = check
            if check.ok:
                log.append({"attempt": attempt, "result": "ok", "tiles": len(good)})
                if mapper is not None:
                    shape = getattr(frame, "shape", None)
                    size = (int(shape[1]), int(shape[0])) if shape is not None else None
                    mapper.update(good, frame_size=size)
                return RefreshResult(True, good, attempt, None, check=check, attempt_log=tuple(log))

            error = ERR_STATE_MISMATCH
            log.append({"attempt": attempt, "result": "mismatch", "problems": list(check.problems)})

        if attempt < max_attempts:
            sleep(retry_delay)

    _clear(mapper)
    return RefreshResult(
        False, last_boxes, max_attempts, error,
        low_confidence=last_low, check=last_check, attempt_log=tuple(log),
    )


def _clear(mapper: Any | None) -> None:
    if mapper is not None:
        mapper.update(())


def log_refresh_result(
    logger: AppLogger | None, game_id: str, event_id: str, result: RefreshResult
) -> None:
    """把重拍結果寫進 JSONL（成功是 system_info，失敗是 warning）。"""
    if logger is None:
        return

    event = create_event(
        event_id=event_id,
        game_id=game_id,
        event_type=EventType.SYSTEM_INFO if result.ok else EventType.WARNING,
        source=EventSource.INTEGRATION,
        payload={
            "kind": "hand_refresh",
            "ok": result.ok,
            "attempts": result.attempts,
            "error": result.error,
            "attempt_log": list(result.attempt_log),
        },
    )
    message = f"Hand refresh ok after {result.attempts} attempt(s)." if result.ok else (
        f"Hand refresh failed: {result.error} after {result.attempts} attempt(s)."
    )
    logger.log_event(event, console_message=message)


# ------------------------------------------------------------ 狀態重建入口

@dataclass(frozen=True)
class RebuildResult:
    state: Any  # 新的 rules.GameState
    added: tuple[int, ...]  # 畫面有、舊狀態沒有
    removed: tuple[int, ...]  # 舊狀態有、畫面沒有

    @property
    def changed(self) -> bool:
        return bool(self.added or self.removed)


def rebuild_own_hand(state: Any, seat: int, visible_hand: Iterable[int]) -> RebuildResult:
    """用畫面確認的手牌覆寫自己的手牌（深拷貝，不改傳入的 state）。"""
    if seat not in state.players:
        raise ValueError(f"unknown seat: {seat}")

    visible = list(visible_hand)
    old = Counter(state.players[seat].hand)
    new = Counter(visible)

    rebuilt = state.model_copy(deep=True)
    rebuilt.players[seat].hand = visible

    return RebuildResult(
        state=rebuilt,
        added=tuple(sorted((new - old).elements())),
        removed=tuple(sorted((old - new).elements())),
    )


def rebuild_from_refresh(state: Any, seat: int, result: RefreshResult) -> RebuildResult:
    """只接受 refresh_hand 成功的結果；失敗的畫面不能拿來重建。"""
    if not result.ok:
        raise ValueError(f"refresh 沒有成功（{result.error}），不能重建狀態")
    return rebuild_own_hand(state, seat, [b.tile for b in result.boxes])