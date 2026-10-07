"""共用動作執行器（W4）：計畫 -> 安全檢查 -> 依序點擊 -> ActionReceipt + JSONL。

出牌（discard_executor）與反應（pipeline.run_reaction_turn）都走這裡。
- 計畫可以有多個點擊（例如「吃」→ 選組合）。
- 每次點擊前都檢查前景視窗與 controller 狀態；失敗也會產生 success=False 的回執，不盲點。
- 已完成部分點擊才失敗（例如第二步被暫停）：ui_action_executed=True、should_stop=True，
  因為畫面可能停在選單中間，不要自動繼續下一個動作。
- state_verified 固定 False：點擊後重新擷取驗證、等待畫面變化、逾時、重試是 W4 D3 以後。
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from src.common.events import EventSource, EventType, create_event, event_from_model
from src.common.logger import AppLogger
from src.common.schemas import ActionReceipt
from src.common.schemas import LegalAction as SchemaLegalAction
from src.control.button_mapper import (
    ButtonDisabledError,
    ButtonNotFoundError,
    ButtonOutOfFrameError,
    ChoiceNotFoundError,
)
from src.control.controller import AgentController
from src.control.tile_mapper import (
    Point,
    TileMappingError,
    TileNotFoundError,
    TileOutOfFrameError,
    UnsupportedActionError,
)

ERR_UNSUPPORTED_ACTION = "UNSUPPORTED_ACTION"
ERR_TILE_NOT_FOUND = "TILE_NOT_FOUND"
ERR_TILE_OUT_OF_FRAME = "TILE_OUT_OF_FRAME"
ERR_BUTTON_NOT_FOUND = "BUTTON_NOT_FOUND"
ERR_BUTTON_DISABLED = "BUTTON_DISABLED"
ERR_BUTTON_OUT_OF_FRAME = "BUTTON_OUT_OF_FRAME"
ERR_CHOICE_NOT_FOUND = "CHOICE_NOT_FOUND"
ERR_WINDOW_NOT_FOREGROUND = "WINDOW_NOT_FOREGROUND"
ERR_CONTROLLER_NOT_RUNNING = "CONTROLLER_NOT_RUNNING"
ERR_MAPPING = "TILE_MAPPING_ERROR"


def mapping_error_code(exc: TileMappingError) -> str:
    if isinstance(exc, UnsupportedActionError):
        return ERR_UNSUPPORTED_ACTION
    if isinstance(exc, TileNotFoundError):
        return ERR_TILE_NOT_FOUND
    if isinstance(exc, TileOutOfFrameError):
        return ERR_TILE_OUT_OF_FRAME
    if isinstance(exc, ButtonDisabledError):
        return ERR_BUTTON_DISABLED
    if isinstance(exc, ButtonNotFoundError):
        return ERR_BUTTON_NOT_FOUND
    if isinstance(exc, ButtonOutOfFrameError):
        return ERR_BUTTON_OUT_OF_FRAME
    if isinstance(exc, ChoiceNotFoundError):
        return ERR_CHOICE_NOT_FOUND
    return ERR_MAPPING


@dataclass(frozen=True)
class PlannedClicks:
    """要依序點擊的座標；detail 放原本的計畫物件（ClickPlan / ReactionPlan），方便呼叫端取用。"""

    frame_points: tuple[Point, ...]
    screen_points: tuple[Point, ...]
    detail: Any = None

    def __post_init__(self) -> None:
        if not self.screen_points or len(self.frame_points) != len(self.screen_points):
            raise ValueError("frame_points 與 screen_points 必須一樣長且至少一個點")


def execute_action(
    action_id: str,
    tile: int | None,
    plan_fn: Callable[[], PlannedClicks],
    controller: AgentController,
    *,
    game_id: str,
    decision_id: str,
    schema_action: SchemaLegalAction | None,
    next_event_id: Callable[[], str],
    logger: AppLogger | None = None,
    parent_event_id: str | None = None,
    foreground_check: Callable[[], bool] | None = None,
    step_delay: float = 0.0,
) -> tuple[ActionReceipt, PlannedClicks | None]:
    """執行一個動作的所有點擊，回傳 (回執, 點擊計畫)。計畫失敗時第二個值為 None。

    plan_fn 失敗時要拋 TileMappingError（含 ButtonMappingError）。
    step_delay：多步驟點擊之間等待的秒數（讓網頁有時間更新）。
    """
    started_at = datetime.now(timezone.utc)
    t0 = time.perf_counter()

    plan: PlannedClicks | None = None
    clicks_done = 0
    error_code: str | None = None
    error_message: str | None = None
    should_stop = False

    started_event_id = next_event_id()

    # 1. 規劃座標
    try:
        plan = plan_fn()
    except TileMappingError as exc:
        error_code = mapping_error_code(exc)
        error_message = str(exc)

    # 2. action_started
    if logger is not None:
        payload: dict[str, Any] = {"action_id": action_id, "tile": tile}
        if plan is not None:
            payload["frame_points"] = [list(p) for p in plan.frame_points]
            payload["screen_points"] = [list(p) for p in plan.screen_points]
            # 相容 W3 的欄位（第一個點）
            payload["frame_point"] = list(plan.frame_points[0])
            payload["screen_point"] = list(plan.screen_points[0])
        logger.log_event(
            create_event(
                event_id=started_event_id,
                game_id=game_id,
                event_type=EventType.ACTION_STARTED,
                source=EventSource.INTEGRATION,
                payload=payload,
                parent_event_id=parent_event_id,
            ),
            console_message=f"Action started: {action_id}",
        )

    # 3. 安全檢查 + 依序點擊（每一步都檢查）
    total = len(plan.screen_points) if plan is not None else 0
    if plan is not None:
        for index, point in enumerate(plan.screen_points):
            if index > 0 and step_delay > 0:
                time.sleep(step_delay)

            if foreground_check is not None and not foreground_check():
                error_code = ERR_WINDOW_NOT_FOREGROUND
                error_message = "目標視窗不在前景，已拒絕點擊"
                should_stop = True  # 企劃書：視窗不在前景 -> 停止操作並重定位
                break

            if not controller.click(*point):
                error_code = ERR_CONTROLLER_NOT_RUNNING
                error_message = f"controller 狀態為 {controller.state.value}，已拒絕點擊"
                break

            clicks_done += 1

    success = plan is not None and clicks_done == total

    # 做到一半失敗：畫面可能停在選單中間，要求停止
    if plan is not None and 0 < clicks_done < total:
        should_stop = True
        error_message = f"{error_message}（已完成 {clicks_done}/{total} 次點擊）"

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
        success=success,
        ui_action_executed=clicks_done > 0,
        state_verified=False,  # W4 D3 才會重新擷取驗證
        latency_ms=latency_ms,
        error_code=error_code,
        error_message=error_message,
        should_stop=should_stop,
    )

    if logger is not None:
        if success and plan is not None:
            message = "Action completed: click " + ", ".join(str(p) for p in plan.screen_points)
        else:
            message = f"Action failed: {error_code}"
        logger.log_event(
            event_from_model(
                event_id=receipt_event_id,
                game_id=game_id,
                event_type=EventType.ACTION_COMPLETED if success else EventType.ACTION_FAILED,
                source=EventSource.INTEGRATION,
                model=receipt,
                parent_event_id=started_event_id,
            ),
            console_message=message,
        )

    return receipt, plan