from src.common.events import (
    EventSource,
    EventType,
    event_from_model,
)
from src.common.logger import AppLogger
from src.common.schemas import (
    ActionReceipt,
    ActionType,
    Decision,
    GameState,
    LegalAction,
    LegalActions,
    Observation,
    Tile,
)


def main() -> None:
    game_id = "game_001"

    with AppLogger(
        log_dir="logs",
        game_id=game_id,
    ) as logger:

        # --------------------------------------------------
        # 1. Observation
        # --------------------------------------------------
        observation = Observation(
            observation_id="obs_001",
            game_id=game_id,
            event_id="evt_001",
            visible_tiles=[
                Tile(tile_id=1, name="一萬", code="1m"),
                Tile(tile_id=2, name="二萬", code="2m"),
            ],
            confidence=0.98,
            is_stable=True,
            is_animating=False,
        )

        observation_event = event_from_model(
            event_id="evt_001",
            game_id=game_id,
            event_type=EventType.OBSERVATION_CREATED,
            source=EventSource.VISION,
            model=observation,
        )

        logger.log_event(
            observation_event,
            console_message="Observation created.",
        )

        # --------------------------------------------------
        # 2. GameState
        # --------------------------------------------------
        game_state = GameState(
            game_id=game_id,
            event_id="evt_002",
            is_our_turn=True,
        )

        state_event = event_from_model(
            event_id="evt_002",
            game_id=game_id,
            event_type=EventType.STATE_UPDATED,
            source=EventSource.RULES,
            model=game_state,
            parent_event_id=observation_event.event_id,
        )

        logger.log_event(
            state_event,
            console_message="GameState updated.",
        )

        # --------------------------------------------------
        # 3. LegalActions
        # --------------------------------------------------
        discard_action = LegalAction(
            action_id="action_001",
            action_type=ActionType.DISCARD,
            tile_ids=[1],
            reason="打出一萬",
        )

        legal_actions = LegalActions(
            game_id=game_id,
            event_id="evt_003",
            state_event_id=state_event.event_id,
            actions=[discard_action],
        )

        legal_actions_event = event_from_model(
            event_id="evt_003",
            game_id=game_id,
            event_type=EventType.LEGAL_ACTIONS_GENERATED,
            source=EventSource.RULES,
            model=legal_actions,
            parent_event_id=state_event.event_id,
        )

        logger.log_event(
            legal_actions_event,
            console_message="Legal actions generated.",
        )

        # --------------------------------------------------
        # 4. Decision
        # --------------------------------------------------
        decision = Decision(
            decision_id="decision_001",
            game_id=game_id,
            event_id="evt_004",
            legal_actions_event_id=legal_actions_event.event_id,
            selected_action=discard_action,
            confidence=0.95,
            reason="優先打出孤張一萬",
            approved_for_execution=True,
        )

        decision_event = event_from_model(
            event_id="evt_004",
            game_id=game_id,
            event_type=EventType.DECISION_MADE,
            source=EventSource.STRATEGY,
            model=decision,
            parent_event_id=legal_actions_event.event_id,
        )

        logger.log_event(
            decision_event,
            console_message="Decision made: discard tile 1.",
        )

        # --------------------------------------------------
        # 5. ActionReceipt
        # --------------------------------------------------
        receipt = ActionReceipt(
            receipt_id="receipt_001",
            game_id=game_id,
            event_id="evt_005",
            decision_id=decision.decision_id,
            action=discard_action,
            success=True,
            ui_action_executed=True,
            state_verified=True,
            latency_ms=350.0,
            verification_observation_event_id="evt_006",
        )

        receipt_event = event_from_model(
            event_id="evt_005",
            game_id=game_id,
            event_type=EventType.ACTION_COMPLETED,
            source=EventSource.INTEGRATION,
            model=receipt,
            parent_event_id=decision_event.event_id,
        )

        logger.log_event(
            receipt_event,
            console_message="Action completed successfully.",
        )


if __name__ == "__main__":
    main()