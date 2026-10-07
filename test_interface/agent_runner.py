"""W2 最小串接：假 GameState → 策略 → 點擊 → ActionReceipt → JSONL。

流程（全部使用各模組已存在的真實介面，不再使用 mock_strategy / mock_controller）：

    rules.GameState（假資料）
        -> strategy.adapters.game_state_to_observation
        -> rules.LegalActionGenerator
        -> strategy.adapters.actions_to_legal_actions
        -> strategy.BaselinePolicy.decide
        -> AgentController.click（預設 FakeMouse，不會真的動滑鼠）
        -> common.schemas.ActionReceipt
        -> logs/<game_id>.jsonl

注意：
- 牌 -> 螢幕座標目前是「假映射」，W3 D3 會換成真正的座標映射。
- W2 沒有重新擷取畫面驗證，所以 receipt.state_verified 固定為 False。
"""

from __future__ import annotations

import time
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any

from src.common.events import EventSource, EventType, create_event, event_from_model
from src.common.logger import AppLogger
from src.common.schemas import ActionReceipt, ActionType
from src.common.schemas import Decision as SchemaDecision
from src.common.schemas import LegalAction as SchemaLegalAction
from src.common.schemas import LegalActions as SchemaLegalActions
from src.control.controller import AgentController
from src.rules.game_state import GameState, PlayerState
from src.rules.legal_actions import LegalActionGenerator
from src.strategy.adapters import actions_to_legal_actions, game_state_to_observation
from src.strategy.baseline import BaselinePolicy
from src.strategy.interfaces import LegalAction as StrategyLegalAction
from src.control.pipeline import EventIds as _EventIds
from src.control.pipeline import to_schema_action as _to_schema_action

# 假座標映射（W3 D3 會由真正的手牌 bbox 映射取代）
FAKE_HAND_START_X = 300
FAKE_HAND_STEP_X = 180
FAKE_HAND_Y = 1660

SEAT = 0


class FakeMouse:
    """記錄點擊位置，不會真的操作滑鼠。"""

    def __init__(self) -> None:
        self.clicks: list[tuple[int, int]] = []

    def click(self, x: int, y: int) -> None:
        self.clicks.append((x, y))


def make_fake_game_state(game_id: str) -> GameState:
    """固定的假牌局：輪到玩家 0，剛摸牌後手牌 17 張。"""
    hand = [0, 1, 2, 3, 4, 5, 9, 10, 11, 18, 19, 20, 27, 27, 31, 31, 33]

    return GameState(
        game_id=game_id,
        current_turn=SEAT,
        wall_count=80,
        players={
            0: PlayerState(seat_id=0, hand=hand),
            1: PlayerState(seat_id=1),
            2: PlayerState(seat_id=2),
            3: PlayerState(seat_id=3),
        },
    )


def fake_tile_to_click_point(hand: list[int], tile: int) -> tuple[int, int]:
    """假映射：手牌由小到大排序後，依序橫向排列。"""
    index = sorted(hand).index(tile)
    return FAKE_HAND_START_X + index * FAKE_HAND_STEP_X, FAKE_HAND_Y


def _failure(message: str, **extra: Any) -> dict[str, Any]:
    return {
        "success": False,
        "observation": extra.get("observation"),
        "decision": extra.get("decision"),
        "execution": extra.get("execution"),
        "receipt": extra.get("receipt"),
        "message": message,
    }


def run_agent(
    *,
    log_dir: str = "logs",
    game_id: str | None = None,
    mouse: Any | None = None,
) -> dict[str, Any]:
    """執行一次：假牌局 -> 決策 -> 模擬點擊 -> 回執 -> JSONL。"""
    if game_id is None:
        game_id = "fake_" + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    mouse = mouse if mouse is not None else FakeMouse()
    ids = _EventIds()

    with AppLogger(log_dir=log_dir, game_id=game_id) as logger:
        controller = AgentController(game_id=game_id, mouse=mouse, logger=logger)
        controller.start()

        try:
            return _run_one_turn(game_id, controller, logger, ids)
        finally:
            controller.stop()


def _run_one_turn(
    game_id: str,
    controller: AgentController,
    logger: AppLogger,
    ids: _EventIds,
) -> dict[str, Any]:
    # 1. 假 GameState -> Observation
    state = make_fake_game_state(game_id)
    hand = state.players[SEAT].hand
    observation = game_state_to_observation(state, seat=SEAT)
    observation_dict = asdict(observation)

    state_event = create_event(
        event_id=ids.next(),
        game_id=game_id,
        event_type=EventType.STATE_UPDATED,
        source=EventSource.RULES,
        payload={
            "seat": SEAT,
            "current_turn": state.current_turn,
            "hand": list(hand),
            "wall_count": state.wall_count,
        },
    )
    logger.log_event(state_event, console_message="Fake game state created.")

    # 2. 規則模組產生合法動作 -> 轉成策略介面
    rules_actions = LegalActionGenerator().get_turn_player_actions(hand=list(hand))
    legal_actions = actions_to_legal_actions(rules_actions)

    if not legal_actions:
        return _failure("沒有可執行的合法動作", observation=observation_dict)

    schema_actions = [_to_schema_action(a) for a in legal_actions]
    legal_event_id = ids.next()
    legal_event = event_from_model(
        event_id=legal_event_id,
        game_id=game_id,
        event_type=EventType.LEGAL_ACTIONS_GENERATED,
        source=EventSource.RULES,
        model=SchemaLegalActions(
            game_id=game_id,
            event_id=legal_event_id,
            state_event_id=state_event.event_id,
            actions=schema_actions,
        ),
        parent_event_id=state_event.event_id,
    )
    logger.log_event(legal_event, console_message=f"{len(legal_actions)} legal actions.")

    # 3. 策略決策
    decision = BaselinePolicy().decide(observation, legal_actions)
    selected = decision.action
    selected_schema = _to_schema_action(selected)

    decision_id = f"decision_{ids.next()}"
    decision_event_id = ids.next()
    decision_event = event_from_model(
        event_id=decision_event_id,
        game_id=game_id,
        event_type=EventType.DECISION_MADE,
        source=EventSource.STRATEGY,
        model=SchemaDecision(
            decision_id=decision_id,
            game_id=game_id,
            event_id=decision_event_id,
            legal_actions_event_id=legal_event.event_id,
            selected_action=selected_schema,
            confidence=min(max(decision.score, 0.0), 1.0),
            reason=decision.reason,
            strategy_version="baseline_v0",
            approved_for_execution=True,
        ),
        parent_event_id=legal_event.event_id,
    )
    logger.log_event(decision_event, console_message=f"Decision: {selected.id}")

    decision_dict = {
        "success": True,
        "action": {
            "type": ActionType(selected.action).value,
            "tile": selected.tile,
            "id": selected.id,
        },
        "score": decision.score,
        "reason": decision.reason,
        "message": "策略已選擇動作",
    }

    # 4. 點擊（W2 只支援出牌）
    started_at = datetime.now(timezone.utc)
    t0 = time.perf_counter()

    clicked = False
    click_point: tuple[int, int] | None = None
    error_code: str | None = None
    error_message: str | None = None

    if ActionType(selected.action) != ActionType.DISCARD or selected.tile is None:
        error_code = "UNSUPPORTED_ACTION"
        error_message = f"W2 只支援出牌，收到 {selected.id}"
    else:
        click_point = fake_tile_to_click_point(list(hand), selected.tile)
        clicked = controller.click(*click_point)
        if not clicked:
            error_code = "CONTROLLER_NOT_RUNNING"
            error_message = f"controller 狀態為 {controller.state.value}，已拒絕點擊"

    latency_ms = (time.perf_counter() - t0) * 1000.0

    # 5. 回執
    receipt_event_id = ids.next()
    receipt = ActionReceipt(
        receipt_id=f"receipt_{receipt_event_id}",
        game_id=game_id,
        event_id=receipt_event_id,
        decision_id=decision_id,
        action=selected_schema,
        started_at=started_at,
        finished_at=datetime.now(timezone.utc),
        success=clicked,
        ui_action_executed=clicked,
        state_verified=False,  # W2 尚未重新擷取畫面驗證
        latency_ms=latency_ms,
        error_code=error_code,
        error_message=error_message,
    )

    logger.log_event(
        event_from_model(
            event_id=receipt_event_id,
            game_id=game_id,
            event_type=EventType.ACTION_COMPLETED if clicked else EventType.ACTION_FAILED,
            source=EventSource.INTEGRATION,
            model=receipt,
            parent_event_id=decision_event.event_id,
        ),
        console_message="Action completed." if clicked else f"Action failed: {error_code}",
    )

    execution_dict = {
        "success": clicked,
        "message": (
            f"測試模式：模擬點擊牌 {selected.tile}，座標 {click_point}"
            if clicked
            else (error_message or "點擊失敗")
        ),
        "clicked_tile": selected.tile if clicked else None,
        "click": {"x": click_point[0], "y": click_point[1]} if click_point else None,
    }

    return {
        "success": clicked,
        "observation": observation_dict,
        "decision": decision_dict,
        "execution": execution_dict,
        "receipt": receipt.model_dump(mode="json"),
        "message": execution_dict["message"],
    }