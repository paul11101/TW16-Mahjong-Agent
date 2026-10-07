"""整合管線：一次出牌回合的共用流程（W3 D5）。

    GameState -> Observation -> 合法動作 -> 策略決策 -> execute_discard（點擊 + 回執）
    每一步都寫 JSONL：state_updated -> legal_actions_generated -> decision_made
                      -> action_started -> action_completed / action_failed

不依賴視窗與網頁：牌框由呼叫端提供（TileMapper）、滑鼠由 controller 提供，
所以可以直接用假滑鼠測試。實機入口見 test_interface/run_auto_discard.py。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from src.common.events import EventSource, EventType, create_event, event_from_model
from src.common.logger import AppLogger
from src.common.schemas import ActionReceipt
from src.common.schemas import Decision as SchemaDecision
from src.common.schemas import LegalAction as SchemaLegalAction
from src.common.schemas import LegalActions as SchemaLegalActions
from src.control.capture import CaptureRegion
from src.control.controller import AgentController
from src.control.discard_executor import execute_discard
from src.control.tile_mapper import ClickPlan, TileMapper
from src.rules.game_state import GameState
from src.rules.legal_actions import LegalActionGenerator
from src.strategy.adapters import actions_to_legal_actions, game_state_to_observation
from src.strategy.baseline import BaselinePolicy
from src.strategy.interfaces import Decision
from src.strategy.interfaces import LegalAction as StrategyLegalAction

ERR_NO_LEGAL_ACTIONS = "NO_LEGAL_ACTIONS"


class EventIds:
    """產生遞增的 event id，例如 run_0001。"""

    def __init__(self, prefix: str = "run") -> None:
        self.prefix = prefix
        self._n = 0

    def next(self) -> str:
        self._n += 1
        return f"{self.prefix}_{self._n:04d}"


def to_schema_action(action: StrategyLegalAction) -> SchemaLegalAction:
    """策略模組的 LegalAction -> 共用 schemas 的 LegalAction（給事件與回執使用）。"""
    if action.tiles:
        tile_ids = list(action.tiles)
    elif action.tile is not None:
        tile_ids = [action.tile]
    else:
        tile_ids = []

    return SchemaLegalAction(
        action_id=action.id,
        action_type=action.action,
        tile_ids=tile_ids,
    )


@dataclass(frozen=True)
class TurnResult:
    """一回合的結果。沒有合法動作時 decision / receipt / plan 都是 None，error 有值。"""

    legal_count: int
    decision: Decision | None = None
    receipt: ActionReceipt | None = None
    plan: ClickPlan | None = None
    error: str | None = None

    @property
    def success(self) -> bool:
        return self.receipt is not None and self.receipt.success


def _log(logger: AppLogger | None, event, message: str) -> None:
    if logger is not None:
        logger.log_event(event, console_message=message)


def run_discard_turn(
    state: GameState,
    seat: int,
    mapper: TileMapper,
    region: CaptureRegion,
    controller: AgentController,
    *,
    game_id: str,
    ids: EventIds,
    logger: AppLogger | None = None,
    policy=None,
    foreground_check: Callable[[], bool] | None = None,
) -> TurnResult:
    """跑一次出牌回合。失敗也會留下回執與 JSONL，不會直接拋錯。"""
    policy = policy or BaselinePolicy()
    hand = list(state.players[seat].hand)
    observation = game_state_to_observation(state, seat=seat)

    # 1. 狀態事件
    state_event = create_event(
        event_id=ids.next(),
        game_id=game_id,
        event_type=EventType.STATE_UPDATED,
        source=EventSource.RULES,
        payload={
            "seat": seat,
            "current_turn": state.current_turn,
            "hand": hand,
            "wall_count": state.wall_count,
        },
    )
    _log(logger, state_event, "State updated.")

    # 2. 合法動作（規則模組在沒有可打的牌時會拋 ValueError，視同沒有合法動作）
    try:
        rules_actions = LegalActionGenerator().get_turn_player_actions(hand=hand)
    except ValueError as exc:
        if logger is not None:
            logger.warning(f"沒有可執行的合法動作：{exc}")
        return TurnResult(legal_count=0, error=ERR_NO_LEGAL_ACTIONS)

    legal = actions_to_legal_actions(rules_actions)
    if not legal:
        if logger is not None:
            logger.warning("沒有可執行的合法動作")
        return TurnResult(legal_count=0, error=ERR_NO_LEGAL_ACTIONS)

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
            actions=[to_schema_action(a) for a in legal],
        ),
        parent_event_id=state_event.event_id,
    )
    _log(logger, legal_event, f"{len(legal)} legal actions.")

    # 3. 策略決策
    decision = policy.decide(observation, legal)
    selected_schema = to_schema_action(decision.action)
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
            legal_actions_event_id=legal_event_id,
            selected_action=selected_schema,
            confidence=min(max(decision.score, 0.0), 1.0),
            reason=decision.reason,
            strategy_version="baseline_v0",
            approved_for_execution=True,
        ),
        parent_event_id=legal_event_id,
    )
    _log(logger, decision_event, f"Decision: {decision.action.id}")

    # 4. 點擊 + 回執
    receipt, plan = execute_discard(
        decision,
        mapper,
        region,
        controller,
        game_id=game_id,
        decision_id=decision_id,
        schema_action=selected_schema,
        next_event_id=ids.next,
        logger=logger,
        parent_event_id=decision_event_id,
        foreground_check=foreground_check,
    )

    return TurnResult(
        legal_count=len(legal),
        decision=decision,
        receipt=receipt,
        plan=plan,
        error=receipt.error_code,
    )