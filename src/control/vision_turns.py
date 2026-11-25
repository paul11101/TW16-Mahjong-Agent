"""真實遊戲的回合函式（W8）：只靠畫面，沒有任何「真實狀態」可以對照。

出牌回合：
    VisionObserver 的 Snapshot（已判定輪到自己、17 張）
    -> 手牌牌 ID（來自視覺）-> 建立最小 GameState
    -> confirm=True：再重拍一次並要求和第一次讀到的手牌一致（多幀確認），不一致就暫停
       confirm=False：直接用這次的牌框（省一次辨識時間），低信心就暫停
    -> run_discard_turn（決策 + 點擊 + 畫面驗證）

反應回合：畫面上看得到的按鈕才處理。沒有河牌資訊，無法自己算吃碰要不要，所以只做兩件事：
    有「胡」按鈕 -> 點胡（遊戲只會在真的能胡時顯示）
    否則有「過」按鈕 -> 點過（不用等遊戲逾時）
    其他（只有吃／碰、沒有過）-> 略過，不點擊
click_reactions=False 時一律略過（舊行為）。
"""

from __future__ import annotations

import time
from typing import Any, Callable, Iterable
from pathlib import Path

from src.common.schemas import ActionType
from src.control.action_executor import PlannedClicks, execute_action
from src.control.button_mapper import ButtonMapper, plan_reaction_click
from src.control.capture import CaptureRegion
from src.control.errors import ERR_LOW_CONFIDENCE
from src.control.event_log import log_info
from src.control.game_profile import state_from_visible_hand
from src.control.game_runner import PHASE_MY_TURN, PHASE_REACTION, Snapshot
from src.control.pipeline import EventIds, TurnResult, run_discard_turn, to_schema_action
from src.control.turn_prep import prepare_turn
from src.control.vision_adapter import boxes_from_buttons, boxes_from_cards, button_action
from src.strategy.action_policy import ActionPolicy
from src.strategy.interfaces import Decision, LegalAction


def pick_reaction_button(actions: Iterable[str]) -> str | None:
    """畫面上有哪些按鈕 -> 要點哪個（win > pass）；沒有可點的回傳 None。"""
    found = set(actions)
    if "win" in found:
        return "win"
    if "pass" in found:
        return "pass"
    return None


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
    click_reactions: bool = True,
    min_win_confidence: float = 0.75,
    win_cooldown: float = 20.0,
    min_button_x: float = 0.6,
    debug_dir: str | None = None,
    clock: Callable[[], float] = time.monotonic,
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

    shared: dict[str, Any] = {"last_win": None, "shots": 0}

    def usable(state: dict, back: float):
        """原始按鈕 -> ButtonBox。擋掉：信心不夠的「胡」、畫面左半邊的按鈕（牌桌空白處的誤判）。"""
        width = (getattr(mapper, "frame_size", None) or (0, 0))[0]
        raw = []
        for b in state.get("action_buttons", []):
            confidence = float(b.get("confidence", 0.0))
            if button_action(b.get("name", "")) == "win" and confidence < min_win_confidence:
                continue
            x, _, w, _ = b.get("bbox", (0, 0, 0, 0))
            if width and (x + w / 2) * back < min_button_x * width:
                continue  # 真正的按鈕在畫面右側（實測約 0.68～0.87）
            raw.append(b)
        return boxes_from_buttons(raw, back)

    def choose(boxes):
        found = {b.action for b in boxes}
        last = shared["last_win"]
        if last is not None and clock() - last < win_cooldown:
            found.discard("win")  # 剛點過胡：之後幾秒是動畫／結算，不再點胡
        return pick_reaction_button(found)

    def describe(state: dict) -> list[dict]:
        return [
            {"name": b.get("name"), "confidence": round(float(b.get("confidence", 0.0)), 3),
             "bbox": list(b.get("bbox", ()))}
            for b in state.get("action_buttons", [])
        ]

    def save_debug(frame, boxes, chosen) -> None:
        """存下畫面：紅框 = 要點的按鈕，綠框 = 其他偵測到的按鈕。"""
        if debug_dir is None or frame is None or shared["shots"] >= 30:
            return
        try:
            import cv2
            import numpy as np

            image = np.ascontiguousarray(frame).copy()
            for b in boxes:
                color = (0, 0, 255) if b.action == chosen else (0, 255, 0)
                cv2.rectangle(image, (b.x, b.y), (b.x + b.w, b.y + b.h), color, 3)
                cv2.putText(image, b.action, (b.x, max(b.y - 8, 20)),
                            cv2.FONT_HERSHEY_SIMPLEX, 1.0, color, 2)
            shared["shots"] += 1
            folder = Path(debug_dir)
            folder.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(str(folder / f"{game_id}_react_{shared['shots']}_{chosen or 'skip'}.png"), image)
        except Exception:  # noqa: BLE001  除錯用，不能影響流程
            pass

    def reaction_turn(snap: Snapshot) -> TurnResult:
        data = snap.data or {}
        boxes = usable(data, vision.last_back)
        chosen = choose(boxes) if click_reactions else None
        if chosen is None:
            if click_reactions and data.get("action_buttons"):
                log_info(
                    logger, ids.next, game_id, "vision_reaction_skipped",
                    reason="no_clickable_button", buttons=describe(data),
                )
                if debug_dir is not None:
                    save_debug(
                        controller.capture(),
                        boxes_from_buttons(data["action_buttons"], vision.last_back), None,
                    )
            return TurnResult(legal_count=0, skipped=True)

        frame = None
        if confirm:
            # 多幀確認：重拍再辨識一次，按鈕還在才點（避開動畫、一閃而過的誤判）
            frame = controller.capture()
            if frame is None:
                return TurnResult(legal_count=0, skipped=True)
            data = vision.detect(frame)
            boxes = usable(data, vision.last_back)
            if choose(boxes) != chosen:
                log_info(logger, ids.next, game_id, "vision_reaction_unconfirmed", chosen=chosen)
                return TurnResult(legal_count=0, skipped=True)

        log_info(
            logger, ids.next, game_id, "vision_reaction", chosen=chosen,
            buttons=describe(data),
        )
        save_debug(frame, boxes, chosen)

        button_mapper = ButtonMapper(frame_size=getattr(mapper, "frame_size", None))
        button_mapper.update(boxes)
        action = LegalAction(
            id=chosen, action=ActionType.WIN if chosen == "win" else ActionType.PASS
        )
        decision = Decision(action=action, score=1.0, reason=f"vision reaction: click {chosen}")

        def plan_fn() -> PlannedClicks:
            plan = plan_reaction_click(decision, button_mapper, region)
            return PlannedClicks(plan.frame_points, plan.screen_points, detail=plan)

        receipt, planned = execute_action(
            action.id, None, plan_fn, controller,
            game_id=game_id, decision_id=f"decision_{ids.next()}",
            schema_action=to_schema_action(action),
            next_event_id=ids.next, logger=logger,
            foreground_check=foreground_check, verifier=verifier, retry=retry,
        )
        if chosen == "win" and receipt.ui_action_executed:
            shared["last_win"] = clock()
        return TurnResult(
            legal_count=len(boxes), decision=decision, receipt=receipt,
            plan=planned.detail if planned is not None else None, error=receipt.error_code,
        )

    return {PHASE_MY_TURN: discard_turn, PHASE_REACTION: reaction_turn}