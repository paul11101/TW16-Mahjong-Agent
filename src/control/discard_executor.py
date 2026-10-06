"""執行一次出牌點擊並產生 ActionReceipt（W3 D4）。

流程：
    Decision -> plan_discard_click（牌框 -> 座標）
             -> 安全檢查（controller 狀態、視窗前景）
             -> controller.click
             -> ActionReceipt + JSONL（action_started / action_completed / action_failed）

注意：
- 失敗（找不到牌、不在前景、controller 暫停...）也會產生 success=False 的回執，不盲點。
- state_verified 固定 False：點擊後重新擷取驗證是 W4 D3。
- 只支援出牌，反應按鈕是 W4。
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Callable

from src.common.events import EventSource, EventType, create_event, event_from_model
from src.common.logger import AppLogger
from src.common.schemas import ActionReceipt
from src.common.schemas import LegalAction as SchemaLegalAction
from src.control.capture import CaptureRegion
from src.control.controller import AgentController
from src.control.tile_mapper import (
    ClickPlan,
    TileMapper,
    TileMappingError,
    TileNotFoundError,
    TileOutOfFrameError,
    UnsupportedActionError,
    plan_discard_click,
)

ERR_UNSUPPORTED_ACTION = "UNSUPPORTED_ACTION"
ERR_TILE_NOT_FOUND = "TILE_NOT_FOUND"
ERR_TILE_OUT_OF_FRAME = "TILE_OUT_OF_FRAME"
ERR_WINDOW_NOT_FOREGROUND = "WINDOW_NOT_FOREGROUND"
ERR_CONTROLLER_NOT_RUNNING = "CONTROLLER_NOT_RUNNING"
ERR_MAPPING = "TILE_MAPPING_ERROR"


def _mapping_error_code(exc: TileMappingError) -> str:
    if isinstance(exc, UnsupportedActionError):
        return ERR_UNSUPPORTED_ACTION
    if isinstance(exc, TileNotFoundError):
        return ERR_TILE_NOT_FOUND
    if isinstance(exc, TileOutOfFrameError):
        return ERR_TILE_OUT_OF_FRAME
    return ERR_MAPPING


def execute_discard(
    decision: Any,
    mapper: TileMapper,
    region: CaptureRegion,
    controller: AgentController,
    *,
    game_id: str,
    decision_id: str,
    schema_action: SchemaLegalAction | None,
    next_event_id: Callable[[], str],
    logger: AppLogger | None = None,
    parent_event_id: str | None = None,
    foreground_check: Callable[[], bool] | None = None,
) -> tuple[ActionReceipt, ClickPlan | None]:
    """執行一次出牌點擊，回傳 (回執, 點擊計畫)。計畫失敗時第二個值為 None。"""
    started_at = datetime.now(timezone.utc)
    t0 = time.perf_counter()

    plan: ClickPlan | None = None
    clicked = False
    error_code: str | None = None
    error_message: str | None = None
    should_stop = False

    started_event_id = next_event_id()

    # 1. 規劃點擊座標
    try:
        plan = plan_discard_click(decision, mapper, region)
    except TileMappingError as exc:
        error_code = _mapping_error_code(exc)
        error_message = str(exc)

    # 2. 記錄 action_started（有座標才有意義的 payload）
    if logger is not None:
        payload: dict[str, Any] = {"action_id": decision.action.id, "tile": decision.action.tile}
        if plan is not None:
            payload["frame_point"] = list(plan.frame_point)
            payload["screen_point"] = list(plan.screen_point)
        logger.log_event(
            create_event(
                event_id=started_event_id,
                game_id=game_id,
                event_type=EventType.ACTION_STARTED,
                source=EventSource.INTEGRATION,
                payload=payload,
                parent_event_id=parent_event_id,
            ),
            console_message=f"Action started: {decision.action.id}",
        )

    # 3. 安全檢查 + 點擊
    if plan is not None:
        if foreground_check is not None and not foreground_check():
            error_code = ERR_WINDOW_NOT_FOREGROUND
            error_message = "目標視窗不在前景，已拒絕點擊"
            should_stop = True  # 企劃書：視窗不在前景 -> 停止操作並重定位
        else:
            clicked = controller.click(*plan.screen_point)
            if not clicked:
                error_code = ERR_CONTROLLER_NOT_RUNNING
                error_message = f"controller 狀態為 {controller.state.value}，已拒絕點擊"

    latency_ms = (time.perf_counter() - t0) * 1000.0

    # 4. 回執
    receipt_event_id = next_event_id()
    receipt = ActionReceipt(
        receipt_id=f"receipt_{receipt_event_id}",
        game_id=game_id,
        event_id=receipt_event_id,
        decision_id=decision_id,
        action=schema_action,
        started_at=started_at,
        finished_at=datetime.now(timezone.utc),
        success=clicked,
        ui_action_executed=clicked,
        state_verified=False,  # W4 D3 才會重新擷取驗證
        latency_ms=latency_ms,
        error_code=error_code,
        error_message=error_message,
        should_stop=should_stop,
    )

    if logger is not None:
        logger.log_event(
            event_from_model(
                event_id=receipt_event_id,
                game_id=game_id,
                event_type=EventType.ACTION_COMPLETED if clicked else EventType.ACTION_FAILED,
                source=EventSource.INTEGRATION,
                model=receipt,
                parent_event_id=started_event_id,
            ),
            console_message=(
                f"Action completed: click {plan.screen_point}"
                if clicked and plan is not None
                else f"Action failed: {error_code}"
            ),
        )

    return receipt, plan