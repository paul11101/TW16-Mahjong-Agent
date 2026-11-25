"""真實遊戲的回合函式（W8）：只靠畫面，沒有任何「真實狀態」可以對照。

出牌回合：
    VisionObserver 的 Snapshot（已判定輪到自己、暗牌張數符合副露狀態）
    -> 手牌牌 ID（來自視覺）-> 建立最小 GameState
    -> confirm=True：再重拍一次並要求和第一次讀到的手牌一致（多幀確認），不一致就暫停
       confirm=False：直接用這次的牌框（省一次辨識時間），低信心就暫停
    -> run_discard_turn（決策 + 點擊 + 畫面驗證）

反應回合預設處理畫面可見的胡／過：
    有「胡」按鈕 -> 點胡（遊戲只會在真的能胡時顯示）
    否則有「過」按鈕 -> 點過（不用等遊戲逾時）
    其他（只有吃／碰、沒有過）-> 略過，不點擊
提供 own_melds 時，以畫面上的棄牌提示、規則與策略處理單一吃、碰。
click_reactions=False 時略過反應按鈕。
"""

from __future__ import annotations

import time
from collections import Counter
from typing import Any, Callable, Iterable
from pathlib import Path

from src.common.schemas import ActionType
from src.control.action_executor import PlannedClicks, execute_action
from src.control.button_mapper import ButtonMapper, plan_reaction_click
from src.control.capture import CaptureRegion
from src.control.errors import ERR_LOW_CONFIDENCE, ERR_STATE_MISMATCH
from src.control.event_log import log_info
from src.control.game_profile import state_from_visible_hand
from src.control.game_runner import PHASE_MY_TURN, PHASE_REACTION, Snapshot
from src.control.pipeline import EventIds, TurnResult, run_discard_turn, to_schema_action
from src.control.turn_prep import prepare_turn
from src.control.vision_adapter import (
    MIN_MELD_BUTTON_CONFIDENCE,
    boxes_from_buttons,
    boxes_from_cards,
    button_action,
)
from src.control.vision_melds import (
    MELD_ACTIONS,
    ExpectedMeld,
    MeldVerifier,
    choose_single_meld,
    read_meld_prompt,
)
from src.rules.game_state import Meld
from src.strategy.action_policy import ActionPolicy
from src.strategy.interfaces import Decision, LegalAction

MELD_BUTTONS = frozenset(kind.value for kind in MELD_ACTIONS)


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
    own_melds: list[Meld] | None = None,
    min_win_confidence: float = 0.75,
    win_cooldown: float = 20.0,
    min_button_x: float = 0.6,
    debug_dir: str | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> dict[str, Callable[[Snapshot], TurnResult]]:
    """回傳 GameRunner 的 turn_fns。"""
    policy = policy or ActionPolicy(include_candidate_scores=False)
    shared: dict[str, Any] = {"last_win": None, "shots": 0, "unconfirmed_meld": False}

    def stop_on_unconfirmed_meld() -> TurnResult:
        """副露後暗牌未能確認時，暫停並要求重新從乾淨的牌局開始。"""
        controller.pause()
        return TurnResult(legal_count=0, error=ERR_STATE_MISMATCH)

    def discard_turn(snap: Snapshot) -> TurnResult:
        if shared["unconfirmed_meld"]:
            return stop_on_unconfirmed_meld()
        boxes = boxes_from_cards(snap.data.get("hand_cards", []), vision.last_back)
        tiles = [b.tile for b in boxes]
        state = state_from_visible_hand(game_id, tiles, seat=seat)
        state.players[seat].melds = list(own_melds or ())

        if confirm:
            prepared = prepare_turn(
                controller, guard, mapper, controller.capture, vision.hand_boxes, tiles,
                game_id=game_id, next_event_id=ids.next, logger=logger,
                meld_count=len(state.players[seat].melds),
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

    def usable(state: dict, back: float):
        """原始按鈕 -> ButtonBox。擋掉：信心不夠的「胡」、畫面左半邊的按鈕（牌桌空白處的誤判）。"""
        width = (getattr(mapper, "frame_size", None) or (0, 0))[0]
        raw = []
        for b in state.get("action_buttons", []):
            confidence = float(b.get("confidence", 0.0))
            kind = button_action(b.get("name", ""))
            if kind == "win" and confidence < min_win_confidence:
                continue
            if own_melds is not None and kind in MELD_BUTTONS and confidence < MIN_MELD_BUTTON_CONFIDENCE:
                continue
            x, _, w, _ = b.get("bbox", (0, 0, 0, 0))
            if width and (x + w / 2) * back < min_button_x * width:
                continue  # 真正的按鈕在畫面右側（實測約 0.68～0.87）
            raw.append(b)
        return boxes_from_buttons(raw, back)

    def choose(boxes, data):
        """保持胡優先，副露只交給已啟用的規則與策略評估。"""
        found = {b.action for b in boxes}
        last = shared["last_win"]
        if last is not None and clock() - last < win_cooldown:
            found.discard("win")  # 剛點過胡：之後幾秒是動畫／結算，不再點胡
        chosen = pick_reaction_button(found)
        if chosen == "win":
            return Decision(LegalAction("win", ActionType.WIN), 1.0, "vision reaction: click win"), None
        if own_melds is not None:
            counts = Counter(box.action for box in boxes)
            visible_melds = {kind for kind in MELD_BUTTONS if counts[kind] == 1}
            if visible_melds:
                prompt = read_meld_prompt(data, vision.last_back, seat, len(own_melds), min_confidence)
                if prompt is not None:
                    decision = choose_single_meld(prompt, visible_melds, own_melds, policy, game_id, seat)
                    if decision is not None and (decision.action.action != ActionType.PASS or chosen):
                        return decision, prompt
        if chosen == "pass":
            return Decision(LegalAction("pass", ActionType.PASS), 1.0, "vision reaction: click pass"), None
        return None, None

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
        if shared["unconfirmed_meld"]:
            return stop_on_unconfirmed_meld()
        data = snap.data or {}
        boxes = usable(data, vision.last_back)
        decision, prompt = choose(boxes, data) if click_reactions else (None, None)
        if decision is None:
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

        action = decision.action
        chosen = action.action.value
        is_meld = action.action in MELD_ACTIONS
        frame = None
        if confirm or is_meld:
            # 多幀確認：重拍再辨識一次，按鈕還在才點（避開動畫、一閃而過的誤判）
            frame = controller.capture()
            if frame is None:
                return TurnResult(legal_count=0, skipped=True)
            data = vision.detect(frame)
            boxes = usable(data, vision.last_back)
            fresh, fresh_prompt = choose(boxes, data)
            if (
                data.get("is_animating") or data.get("in_settlement")
                or fresh is None or fresh.action != action or fresh_prompt != prompt
            ):
                log_info(logger, ids.next, game_id, "vision_reaction_unconfirmed", chosen=chosen)
                return TurnResult(legal_count=0, skipped=True)

        log_info(
            logger, ids.next, game_id, "vision_reaction", chosen=chosen,
            buttons=describe(data), action_id=action.id, reason=decision.reason,
            **({"target_tile": prompt.tile, "target_player": prompt.player_id} if prompt else {}),
        )

        button_mapper = ButtonMapper(frame_size=getattr(mapper, "frame_size", None))
        button_mapper.update(boxes)
        expected = ExpectedMeld.from_action(action, prompt) if is_meld else None
        active_verifier = verifier
        if expected is not None:
            active_verifier = MeldVerifier(
                expected, controller, vision, button_mapper.frame_size, len(own_melds) + 1,
                min_confidence=min_confidence, attempts=max(6, refresh_attempts), poll_interval=retry_delay,
                sleep=sleep, clock=clock, foreground_check=foreground_check, base_verifier=verifier,
            )

        def plan_fn() -> PlannedClicks:
            plan = plan_reaction_click(decision, button_mapper, region)
            return PlannedClicks(plan.frame_points, plan.screen_points, detail=plan)

        receipt, planned = execute_action(
            action.id, action.tile, plan_fn, controller,
            game_id=game_id, decision_id=f"decision_{ids.next()}",
            schema_action=to_schema_action(action),
            next_event_id=ids.next, logger=logger,
            foreground_check=foreground_check, verifier=active_verifier,
            retry=None if is_meld else retry,
        )
        if expected is not None and receipt.ui_action_executed:
            if receipt.state_verified:
                own_melds.append(expected.meld)
                log_info(logger, ids.next, game_id, "vision_meld_confirmed",
                         action_id=action.id, meld_count=len(own_melds))
            else:
                shared["unconfirmed_meld"] = True
                log_info(logger, ids.next, game_id, "vision_meld_unconfirmed",
                         action_id=action.id, error=receipt.error_code)
        if chosen == "win" and receipt.ui_action_executed:
            shared["last_win"] = clock()
        save_debug(frame, boxes, chosen)
        return TurnResult(
            legal_count=len(boxes), decision=decision, receipt=receipt,
            plan=planned.detail if planned is not None else None, error=receipt.error_code,
        )

    return {PHASE_MY_TURN: discard_turn, PHASE_REACTION: reaction_turn}
