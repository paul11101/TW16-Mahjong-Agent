"""執行一次出牌點擊並產生 ActionReceipt（W3 D4）。

W4 起實際流程搬到 action_executor.execute_action，這裡只是出牌的薄包裝，
介面與回傳值不變：(ActionReceipt, ClickPlan | None)。
ERR_* 常數仍可從這個模組 import。
"""

from __future__ import annotations

from typing import Any, Callable

from src.common.logger import AppLogger
from src.common.schemas import ActionReceipt
from src.common.schemas import LegalAction as SchemaLegalAction
from src.control.action_executor import (  # noqa: F401  (ERR_* 供舊程式 import)
    ERR_BUTTON_DISABLED,
    ERR_BUTTON_NOT_FOUND,
    ERR_BUTTON_OUT_OF_FRAME,
    ERR_CHOICE_NOT_FOUND,
    ERR_CONTROLLER_NOT_RUNNING,
    ERR_MAPPING,
    ERR_TILE_NOT_FOUND,
    ERR_TILE_OUT_OF_FRAME,
    ERR_UNSUPPORTED_ACTION,
    ERR_WINDOW_NOT_FOREGROUND,
    PlannedClicks,
    execute_action,
)
from src.control.capture import CaptureRegion
from src.control.controller import AgentController
from src.control.tile_mapper import ClickPlan, TileMapper, plan_discard_click


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

    def plan_fn() -> PlannedClicks:
        plan = plan_discard_click(decision, mapper, region)
        return PlannedClicks((plan.frame_point,), (plan.screen_point,), detail=plan)

    receipt, planned = execute_action(
        decision.action.id,
        decision.action.tile,
        plan_fn,
        controller,
        game_id=game_id,
        decision_id=decision_id,
        schema_action=schema_action,
        next_event_id=next_event_id,
        logger=logger,
        parent_event_id=parent_event_id,
        foreground_check=foreground_check,
    )
    return receipt, (planned.detail if planned is not None else None)