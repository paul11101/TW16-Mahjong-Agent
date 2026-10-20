import pytest

from src.common.schemas import ActionType
from src.rules.game_state import GameState, PlayerState
from src.rules.legal_actions import LegalActionGenerator
from src.rules.rule import Action, RuleMechanics, RulesetConfig


def make_players():
    return {seat: PlayerState(seat_id=seat) for seat in range(4)}


def test_auto_flower_replacement_draws_until_non_flower():
    state = GameState(
        game_id="flower-draw-test",
        players=make_players(),
        wall=[8, 34],
    )
    config = RulesetConfig(
        rule_mechanics=RuleMechanics(reserved_wall_tiles=0),
    )

    action = state.draw_tile(config=config)

    assert action == Action(action_type=ActionType.DRAW_TILE, tile_id=8)
    assert state.players[0].flowers == [34]
    assert state.players[0].hand == [8]
    assert state.wall == []
    assert state.wall_count == 0


def test_manual_flower_replacement_does_not_double_decrement_wall():
    state = GameState(
        game_id="manual-flower-draw-test",
        players=make_players(),
        wall=[8, 34],
    )
    config = RulesetConfig(
        rule_mechanics=RuleMechanics(
            reserved_wall_tiles=0,
            auto_flower_replacement=False,
        ),
    )

    flower_action = state.draw_tile(config=config)
    assert flower_action.action_type == ActionType.FLOWER_REPLACEMENT
    assert state.wall_count == 1

    replacement = state.apply_action(0, flower_action, config=config)

    assert replacement == Action(action_type=ActionType.DRAW_TILE, tile_id=8)
    assert state.players[0].flowers == [34]
    assert state.players[0].hand == [8]
    assert state.wall == []
    assert state.wall_count == 0


def test_manual_replacement_handles_consecutive_flowers():
    state = GameState(
        game_id="consecutive-flower-draw-test",
        players=make_players(),
        wall=[8, 35, 34],
    )
    config = RulesetConfig(
        rule_mechanics=RuleMechanics(
            reserved_wall_tiles=0,
            auto_flower_replacement=False,
        ),
    )

    first = state.draw_tile(config=config)
    second = state.apply_action(0, first, config=config)
    final = state.apply_action(0, second, config=config)

    assert first.action_type == ActionType.FLOWER_REPLACEMENT
    assert second.action_type == ActionType.FLOWER_REPLACEMENT
    assert final == Action(action_type=ActionType.DRAW_TILE, tile_id=8)
    assert state.players[0].flowers == [34, 35]
    assert state.players[0].hand == [8]
    assert state.wall == []
    assert state.wall_count == 0


def test_non_current_player_cannot_draw():
    state = GameState(
        game_id="out-of-turn-draw-test",
        current_turn=1,
        players=make_players(),
        wall=[8],
    )
    config = RulesetConfig(
        rule_mechanics=RuleMechanics(reserved_wall_tiles=0),
    )

    with pytest.raises(ValueError, match="It is player 1's turn"):
        state.draw_tile(player_id=0, config=config)

    assert state.wall == [8]
    assert state.players[0].hand == []


def test_fixed_draw_board_distinguishes_flower_from_normal_tile():
    generator = LegalActionGenerator()

    assert generator.get_draw_actions(35).action_type == ActionType.FLOWER_REPLACEMENT
    assert generator.get_draw_actions(8).action_type == ActionType.DRAW_TILE
