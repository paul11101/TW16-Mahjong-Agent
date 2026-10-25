from src.common.schemas import ActionType
from src.rules.game_state import GameState, PlayerState
from src.rules.rule import Action, RulesetConfig


def make_players():
    return {seat: PlayerState(seat_id=seat) for seat in range(4)}


def test_wall_at_reserved_eight_stacks_causes_draw_and_dealer_retention():
    state = GameState(
        game_id="w5-reserved-wall-test",
        dealer=2,
        lian_zhuang=1,
        players=make_players(),
        wall=[8] * 16,
    )

    assert state.draw_tile() is None

    assert state.wall_count == len(state.wall) == 16
    assert state.is_over
    assert state.dealer == 2
    assert state.lian_zhuang == 2


def test_last_drawable_tile_precedes_wall_exhaustion_draw():
    state = GameState(
        game_id="w5-last-drawable-test",
        dealer=1,
        lian_zhuang=3,
        players=make_players(),
        wall=[8] * 17,
    )
    config = RulesetConfig()

    action = state.draw_tile(config=config)

    assert action == Action(action_type=ActionType.DRAW_TILE, tile_id=8)
    assert state.wall_count == len(state.wall) == 16
    assert not state.is_over
    assert state.lian_zhuang == 3

    state.current_turn = 0
    assert state.draw_tile(config=config) is None
    assert state.is_over
    assert state.dealer == 1
    assert state.lian_zhuang == 4


def test_draw_after_last_drawable_tile_retains_dealer_and_current_turn():
    state = GameState(
        game_id="w5-last-drawable-settlement-test",
        dealer=2,
        current_turn=3,
        lian_zhuang=4,
        players=make_players(),
        wall=[8] * 17,
    )

    last_drawable_tile = state.draw_tile()

    assert last_drawable_tile == Action(action_type=ActionType.DRAW_TILE, tile_id=8)
    assert state.current_turn == 3
    assert not state.is_over

    no_more_draws = state.draw_tile()

    assert no_more_draws is None
    assert state.is_over
    assert state.dealer == 2
    assert state.lian_zhuang == 5
    assert state.current_turn == 3
