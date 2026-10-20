from src.common.schemas import ActionType
from src.rules.game_state import GameState, PlayerState
from src.rules.rule import Action, RuleMechanics, RulesetConfig


def test_draw_tile_updates_hand_and_wall_count():
    players = {seat: PlayerState(seat_id=seat) for seat in range(4)}
    state = GameState(
        game_id="draw-test",
        players=players,
        wall=[8],
    )
    config = RulesetConfig(
        rule_mechanics=RuleMechanics(reserved_wall_tiles=0),
    )

    action = state.draw_tile(config=config)

    assert action == Action(action_type=ActionType.DRAW_TILE, tile_id=8)
    assert state.players[0].hand == [8]
    assert state.wall == []
    assert state.wall_count == 0
