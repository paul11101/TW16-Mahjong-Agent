import json

from src.common.schemas import ActionType
from src.common.logger import AppLogger
from src.control.button_mapper import ButtonBox, ButtonMapper
from src.control.capture import CaptureRegion
from src.control.controller import AgentController
from src.control.pipeline import EventIds, get_reaction_rules_actions, run_reaction_turn
from src.rules.game_state import GameState, LastDiscard, PlayerState
from src.strategy.adapters import actions_to_legal_actions

SEAT = 0
WIN_HAND = [0, 1, 2, 3, 3, 4, 5, 6, 9, 10, 11, 18, 19, 20, 27, 27]
PASS_HAND = [0, 1, 2, 3, 3, 4, 5, 6, 9, 10, 11, 18, 19, 20, 27, 30]

class FakeMouse:
    def __init__(self):
        self.clicks = []

    def click(self, x, y):
        self.clicks.append((x, y))


def make_state(hand, target_tile, game_id):
    return GameState(
        game_id = game_id,
        current_turn = SEAT,
        wall_count = 80,
        last_discard = LastDiscard(player_id = 3, tile_id = target_tile),
        players = {
            i: PlayerState(seat_id = i, hand = list(hand) if i == SEAT else [])
            for i in range(4)
        },
    )


def make_mapper():
    mapper = ButtonMapper(frame_size = (800, 600))
    mapper.update(buttons = [
        ButtonBox("win", 100, 100, 40, 20),
        ButtonBox("pass", 200, 100, 40, 20),
    ])

    return mapper


def run_pipeline(state, tmp_path):
    mouse = FakeMouse()

    with AppLogger(log_dir = str(tmp_path), game_id = state.game_id) as logger:
        controller = AgentController(game_id = state.game_id, mouse = mouse, logger = logger,)
        controller.start()

        try:
            result = run_reaction_turn(
                state,
                SEAT,
                make_mapper(),
                CaptureRegion(0, 0, 800, 600),
                controller,
                game_id = state.game_id,
                ids = EventIds(),
                logger = logger,
            )

        finally:
            controller.stop()

    log_path = tmp_path / f"{state.game_id}.jsonl"
    events = [json.loads(line)["event_type"] for line in log_path.read_text(encoding = "utf-8").splitlines()]

    return result, mouse.clicks, events


def test_rules_to_baseline_win(tmp_path):
    state = make_state(WIN_HAND, 3, "w4_d2_win")
    rules_actions = get_reaction_rules_actions(state, SEAT)
    legal = actions_to_legal_actions(rules_actions)
    action_types = {a.action for a in legal}

    assert {ActionType.WIN, ActionType.CHI, ActionType.PONG, ActionType.PASS,} <= action_types

    result, clicks, events = run_pipeline(state, tmp_path)

    assert result.success is True
    assert result.decision.action.action == ActionType.WIN
    assert result.decision.action in legal
    assert result.receipt.success is True
    assert clicks == [(120, 110)]
    assert "legal_actions_generated" in events
    assert "action_completed" in events


def test_rules_to_baseline_pass(tmp_path):
    state = make_state(PASS_HAND, 3, "w4_d2_pass")
    rules_actions = get_reaction_rules_actions(state, SEAT)
    legal = actions_to_legal_actions(rules_actions)
    action_types = {a.action for a in legal}

    assert ActionType.CHI in action_types
    assert ActionType.PONG in action_types
    assert ActionType.PASS in action_types
    assert ActionType.WIN not in action_types

    result, clicks, events = run_pipeline(state, tmp_path)

    assert result.success is True
    assert result.decision.action.action == ActionType.PASS
    assert result.decision.action in legal
    assert  clicks == [(220, 110)]
    assert "decision_made" in events
    assert "action_completed" in events


def test_only_pass_skips_click(tmp_path):
    state = make_state(PASS_HAND, 33, "w4_d2_skip")
    legal = actions_to_legal_actions(get_reaction_rules_actions(state, SEAT))

    assert len(legal) == 1
    assert legal[0].action == ActionType.PASS

    result, clicks, events = run_pipeline(state, tmp_path)

    assert result.skipped is True
    assert result.decision is None
    assert result.receipt is None
    assert clicks == []
    assert "reaction_skipped" in events
    assert "action_started" not in events