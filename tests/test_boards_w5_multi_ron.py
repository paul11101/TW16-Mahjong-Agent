import pytest

from src.common.schemas import ActionType
from src.rules.game_state import GameState, LastDiscard, PlayerState
from src.rules.rule import Action, RuleMechanics, RulesetConfig


def make_reaction_state(target_tile=2):
    players = {seat: PlayerState(seat_id=seat) for seat in range(4)}
    players[0].discards = [target_tile]
    return GameState(
        game_id="w5-multi-ron-test",
        players=players,
        last_discard=LastDiscard(player_id=0, tile_id=target_tile),
    )


def test_multi_winner_returns_all_ron_candidates():
    state = make_reaction_state()
    reactions = {
        1: Action(action_type=ActionType.WIN, tile_id=2),
        2: Action(action_type=ActionType.WIN, tile_id=2),
        3: Action(action_type=ActionType.PONG, tile_id=2),
    }
    config = RulesetConfig(
        rule_mechanics=RuleMechanics(multi_winner=True),
    )

    assert state.resolve_reaction_priority(reactions, config=config) == {
        1: reactions[1],
        2: reactions[2],
    }


def test_multiple_ron_winner_order_wraps_around_seat_zero():
    state = make_reaction_state()
    state.last_discard.player_id = 3
    reactions = {
        0: Action(action_type=ActionType.WIN, tile_id=2),
        2: Action(action_type=ActionType.WIN, tile_id=2),
    }

    assert state.resolve_reaction_priority(reactions) == {0: reactions[0]}


def test_multi_winner_rejects_unsupported_winner_priority():
    state = make_reaction_state()
    config = RulesetConfig(
        rule_mechanics=RuleMechanics(
            multi_winner=True,
            winner_priority="unsupported",
        ),
    )

    with pytest.raises(ValueError, match="Unsupported winner priority"):
        state.resolve_reaction_priority(
            {
                1: Action(action_type=ActionType.WIN, tile_id=2),
                3: Action(action_type=ActionType.WIN, tile_id=2),
            },
            config=config,
        )
