"""真實遊戲的回合函式（W8）：只靠畫面，沒有任何「真實狀態」可以對照。

出牌回合：
    VisionObserver 的 Snapshot（已判定輪到自己、17 張）
    -> 手牌牌 ID（來自視覺）-> 建立最小 GameState
    -> confirm=True：再重拍一次並要求和第一次讀到的手牌一致（多幀確認），不一致就暫停
       confirm=False：直接用這次的牌框（省一次辨識時間），低信心就暫停
    -> run_discard_turn（決策 + 點擊 + 畫面驗證）

反應回合：目前沒有按鈕偵測，一律略過（不點擊）。
"""

from __future__ import annotations

import time
from typing import Any, Callable

from src.control.capture import CaptureRegion
from src.control.errors import ERR_LOW_CONFIDENCE
from src.control.game_profile import state_from_visible_hand
from src.control.game_runner import PHASE_MY_TURN, PHASE_REACTION, Snapshot
from src.control.pipeline import EventIds, TurnResult, run_discard_turn
from src.control.turn_prep import prepare_turn
from src.control.vision_adapter import boxes_from_cards
from src.strategy.action_policy import ActionPolicy


def make_vision_turns(
    controller: Any,
    vision: Any,
    mapper: Any,
    guard: Any,
    region: CaptureRegion,
    *,
    game_id: str,
    ids: EventIds,
    logger: Any | None = None,
    policy: Any | None = None,
    foreground_check: Callable[[], bool] | None = None,
    verifier: Any | None = None,
    retry: Any | None = None,
    confirm: bool = True,
    min_confidence: float = 0.6,
    refresh_attempts: int = 3,
    retry_delay: float = 0.2,
    sleep: Callable[[float], None] = time.sleep,
    seat: int = 0,
) -> dict[str, Callable[[Snapshot], TurnResult]]:
    """回傳 GameRunner 的 turn_fns。"""
    policy = policy or ActionPolicy(include_candidate_scores=False)

    def discard_turn(snap: Snapshot) -> TurnResult:
        boxes = boxes_from_cards(snap.data.get("hand_cards", []), vision.last_back)
        tiles = [b.tile for b in boxes]
        state = state_from_visible_hand(game_id, tiles, seat=seat)

        if confirm:
            prepared = prepare_turn(
                controller, guard, mapper, controller.capture, vision.hand_boxes, tiles,
                game_id=game_id, next_event_id=ids.next, logger=logger,
                max_attempts=refresh_attempts, retry_delay=retry_delay,
                context={"phase": snap.phase}, sleep=sleep,
            )
            if prepared.failure is not None:
                return prepared.failure
        else:
            if any(b.confidence < min_confidence for b in boxes):
                controller.pause()
                return TurnResult(legal_count=0, error=ERR_LOW_CONFIDENCE)
            mapper.update(boxes)

        return run_discard_turn(
            state, seat, mapper, region, controller,
            game_id=game_id, ids=ids, logger=logger, policy=policy,
            foreground_check=foreground_check, verifier=verifier, retry=retry,
        )

    def reaction_turn(snap: Snapshot) -> TurnResult:
        return TurnResult(legal_count=0, skipped=True)

    return {PHASE_MY_TURN: discard_turn, PHASE_REACTION: reaction_turn}