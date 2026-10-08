"""整合管線：一次出牌／反應回合的共用流程（W3 D5、W4 D1）。

出牌回合：
    GameState -> Observation -> 合法動作 -> 策略決策 -> execute_discard（點擊 + 回執）
反應回合（他家打牌後的 吃碰槓胡過）：
    GameState -> Observation -> 反應動作 -> 策略決策 -> execute_action（1~2 次點擊 + 回執）
    只有 PASS 一個選項時不點擊，記 reaction_skipped。

每一步都寫 JSONL：state_updated -> legal_actions_generated -> decision_made
                  -> action_started -> action_completed / action_failed

不依賴視窗與網頁：牌框／按鈕框由呼叫端提供、滑鼠由 controller 提供，
所以可以直接用假滑鼠測試。實機入口見 test_interface/run_auto_discard.py、run_auto_react.py。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from src.common.events import EventSource, EventType, create_event, event_from_model
from src.common.logger import AppLogger
from src.common.schemas import ActionReceipt, ActionType
from src.common.schemas import Decision as SchemaDecision
from src.common.schemas import LegalAction as SchemaLegalAction
from src.common.schemas import LegalActions as SchemaLegalActions
from src.control.action_executor import PlannedClicks, execute_action
from src.control.button_mapper import ButtonMapper, plan_reaction_click
from src.control.capture import CaptureRegion
from src.control.controller import AgentController
from src.control.discard_executor import execute_discard
from src.control.tile_mapper import TileMapper
from src.rules.game_state import GameState, is_basic_win
from src.rules.legal_actions import LegalActionGenerator
from src.strategy.adapters import actions_to_legal_actions, game_state_to_observation
from src.strategy.baseline import BaselinePolicy
from src.strategy.interfaces import Decision
from src.strategy.interfaces import LegalAction as StrategyLegalAction

ERR_NO_LEGAL_ACTIONS = "NO_LEGAL_ACTIONS"
ERR_NO_REACTION_TARGET = "NO_REACTION_TARGET"


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
    """一回合的結果。

    沒有合法動作時 decision / receipt / plan 都是 None，error 有值。
    skipped=True：只有 PASS 可選，依規則不點擊（不算一次 UI 動作，不進操作成功率分母）。
    plan：出牌是 ClickPlan，反應是 ReactionPlan。
    """

    legal_count: int
    decision: Decision | None = None
    receipt: ActionReceipt | None = None
    plan: Any = None
    error: str | None = None
    skipped: bool = False

    @property
    def success(self) -> bool:
        return self.receipt is not None and self.receipt.success


def _log(logger: AppLogger | None, event, message: str) -> None:
    if logger is not None:
        logger.log_event(event, console_message=message)


def _log_state(logger, game_id: str, ids: EventIds, payload: dict[str, Any]):
    event = create_event(
        event_id=ids.next(),
        game_id=game_id,
        event_type=EventType.STATE_UPDATED,
        source=EventSource.RULES,
        payload=payload,
    )
    _log(logger, event, "State updated.")
    return event


def _log_legal(logger, game_id: str, ids: EventIds, state_event_id: str, legal) -> str:
    legal_event_id = ids.next()
    event = event_from_model(
        event_id=legal_event_id,
        game_id=game_id,
        event_type=EventType.LEGAL_ACTIONS_GENERATED,
        source=EventSource.RULES,
        model=SchemaLegalActions(
            game_id=game_id,
            event_id=legal_event_id,
            state_event_id=state_event_id,
            actions=[to_schema_action(a) for a in legal],
        ),
        parent_event_id=state_event_id,
    )
    _log(logger, event, f"{len(legal)} legal actions.")
    return legal_event_id


def _decide_and_log(policy, observation, legal, *, game_id, ids, legal_event_id, logger):
    decision = policy.decide(observation, legal)
    selected_schema = to_schema_action(decision.action)
    decision_id = f"decision_{ids.next()}"
    decision_event_id = ids.next()
    event = event_from_model(
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
            strategy_version=getattr(policy, "strategy_version", "baseline_v0"),
            approved_for_execution=True,
        ),
        parent_event_id=legal_event_id,
    )
    _log(logger, event, f"Decision: {decision.action.id}")
    return decision, selected_schema, decision_id, decision_event_id


# ------------------------------------------------------------------ 出牌

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
    verifier: Any | None = None,
) -> TurnResult:
    """跑一次出牌回合。失敗也會留下回執與 JSONL，不會直接拋錯。"""
    policy = policy or BaselinePolicy()
    hand = list(state.players[seat].hand)
    observation = game_state_to_observation(state, seat=seat)

    state_event = _log_state(
        logger, game_id, ids,
        {"seat": seat, "current_turn": state.current_turn, "hand": hand, "wall_count": state.wall_count},
    )

    # 規則模組在沒有可打的牌時會拋 ValueError，視同沒有合法動作
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

    legal_event_id = _log_legal(logger, game_id, ids, state_event.event_id, legal)
    decision, selected_schema, decision_id, decision_event_id = _decide_and_log(
        policy, observation, legal,
        game_id=game_id, ids=ids, legal_event_id=legal_event_id, logger=logger,
    )

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
        verifier=verifier,
    )

    return TurnResult(
        legal_count=len(legal),
        decision=decision,
        receipt=receipt,
        plan=plan,
        error=receipt.error_code,
    )


# ------------------------------------------------------------------ 反應

def get_reaction_rules_actions(state: GameState, seat: int):
    """【暫時轉接】GameState -> 規則模組的反應動作。

    規則模組目前沒有 get_reaction_actions(state, seat)，所以整合端先自己湊參數
    （上家判斷、可否榮和）。等規則提供後，只要換掉這個函式。
    沒有他家打出的牌時拋 ValueError。
    """
    last = state.last_discard
    if last is None or last.player_id == seat:
        raise ValueError("目前沒有可反應的他家打牌")

    player = state.players[seat]
    hand = list(player.hand)
    target = last.tile_id

    can_win = False
    if 0 <= target < 34:
        try:
            can_win = is_basic_win(hand + [target], meld_count=len(player.melds))
        except ValueError:
            can_win = False

    return LegalActionGenerator().get_response_actions(
        hand=hand,
        target_tile=target,
        is_previous_player=(last.player_id + 1) % 4 == seat,
        can_win_honin=can_win,
    )


def run_reaction_turn(
    state: GameState,
    seat: int,
    mapper: ButtonMapper,
    region: CaptureRegion,
    controller: AgentController,
    *,
    game_id: str,
    ids: EventIds,
    logger: AppLogger | None = None,
    policy=None,
    foreground_check: Callable[[], bool] | None = None,
    step_delay: float = 0.0,
    verifier: Any | None = None,
) -> TurnResult:
    """跑一次反應回合（吃碰槓胡過）。失敗也會留下回執與 JSONL，不會直接拋錯。"""
    policy = policy or BaselinePolicy()
    hand = list(state.players[seat].hand)
    observation = game_state_to_observation(state, seat=seat)
    last = state.last_discard

    state_event = _log_state(
        logger, game_id, ids,
        {
            "seat": seat,
            "current_turn": state.current_turn,
            "hand": hand,
            "wall_count": state.wall_count,
            "last_discard": (
                {"player_id": last.player_id, "tile_id": last.tile_id} if last is not None else None
            ),
        },
    )

    try:
        rules_actions = get_reaction_rules_actions(state, seat)
    except ValueError as exc:
        if logger is not None:
            logger.warning(f"沒有可反應的牌：{exc}")
        return TurnResult(legal_count=0, error=ERR_NO_REACTION_TARGET)

    legal = actions_to_legal_actions(rules_actions)
    if not legal:
        if logger is not None:
            logger.warning("沒有可執行的合法動作")
        return TurnResult(legal_count=0, error=ERR_NO_LEGAL_ACTIONS)

    legal_event_id = _log_legal(logger, game_id, ids, state_event.event_id, legal)

    # 只有 PASS 一個選項：真實遊戲沒有可反應的牌時不會出現按鈕，所以不點擊，記一筆略過
    if all(ActionType(a.action) == ActionType.PASS for a in legal):
        _log(
            logger,
            create_event(
                event_id=ids.next(),
                game_id=game_id,
                event_type=EventType.REACTION_SKIPPED,
                source=EventSource.INTEGRATION,
                payload={"reason": "only_pass", "action_ids": [a.id for a in legal]},
                parent_event_id=legal_event_id,
            ),
            "Reaction skipped: only PASS available.",
        )
        return TurnResult(legal_count=len(legal), skipped=True)

    decision, selected_schema, decision_id, decision_event_id = _decide_and_log(
        policy, observation, legal,
        game_id=game_id, ids=ids, legal_event_id=legal_event_id, logger=logger,
    )

    def plan_fn() -> PlannedClicks:
        plan = plan_reaction_click(decision, mapper, region, legal_actions=legal)
        return PlannedClicks(plan.frame_points, plan.screen_points, detail=plan)

    receipt, planned = execute_action(
        decision.action.id,
        decision.action.tile,
        plan_fn,
        controller,
        game_id=game_id,
        decision_id=decision_id,
        schema_action=selected_schema,
        next_event_id=ids.next,
        logger=logger,
        parent_event_id=decision_event_id,
        foreground_check=foreground_check,
        step_delay=step_delay,
        verifier=verifier,
    )

    return TurnResult(
        legal_count=len(legal),
        decision=decision,
        receipt=receipt,
        plan=planned.detail if planned is not None else None,
        error=receipt.error_code,
    )