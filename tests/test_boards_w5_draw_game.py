from src.common.schemas import ActionType
from src.rules.game_state import GameState, PlayerState
from src.rules.rule import Action, RuleMechanics, RulesetConfig


def make_players():
    return {seat: PlayerState(seat_id=seat) for seat in range(4)}


def test_repeated_wall_exhaustion_does_not_settle_round_twice():
    state = GameState(
        game_id="w5-repeated-wall-exhaustion-test",
        dealer=3,
        current_turn=1,
        lian_zhuang=4,
        players=make_players(),
        wall=[],
    )

    assert state.draw_tile() is None
    assert state.draw_tile() is None

    assert state.is_over
    assert state.dealer == 3
    assert state.lian_zhuang == 5


def test_flower_replacement_that_exhausts_wall_causes_draw():
    state = GameState(
        game_id="w5-flower-wall-exhaustion-test",
        players=make_players(),
        wall=[34],
    )
    config = RulesetConfig(
        rule_mechanics=RuleMechanics(
            reserved_wall_tiles=0,
            auto_flower_replacement=False,
        ),
    )

    flower = state.draw_tile(config=config)
    replacement = state.apply_action(0, flower, config=config)

    assert replacement is None
    assert state.players[0].flowers == [34]
    assert state.players[0].hand == []
    assert state.wall_count == len(state.wall) == 0
    assert state.is_over
    assert state.lian_zhuang == 1
