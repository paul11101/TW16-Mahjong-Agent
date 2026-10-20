import pytest

from src.common.schemas import ActionType
from src.rules.game_state import GameState, LastDiscard, PlayerState
from src.rules.rule import Action, RuleMechanics, RulesetConfig


def make_state(
    *,
    dealer=0,
    current_turn=0,
    wall=None,
    discard_tile=31,
):
    players = {seat: PlayerState(seat_id=seat) for seat in range(4)}
    players[0].discards = [discard_tile]
    players[1].hand = [
        0, 1, 2,
        3, 4, 5,
        9, 10, 11,
        18, 19, 20,
        27, 28, 29,
        discard_tile,
    ]
    return GameState(
        game_id="w4-boundary-test",
        dealer=dealer,
        current_turn=current_turn,
        players=players,
        wall=[] if wall is None else wall,
        last_discard=LastDiscard(player_id=0, tile_id=discard_tile),
    )


def test_passed_win_blocks_ron_until_player_draws_and_discards():
    state = make_state(current_turn=1, wall=[8])
    config = RulesetConfig(
        rule_mechanics=RuleMechanics(reserved_wall_tiles=0),
    )
    win = Action(action_type=ActionType.WIN, tile_id=31)

    state.apply_action(1, Action(action_type=ActionType.PASS), config=config)

    assert state.players[1].passed_win
    assert not state.players[1].has_drawn_since_pass
    with pytest.raises(ValueError, match="False win"):
        state.resolve_reaction_priority({1: win}, config=config)

    state.draw_tile(config=config)
    assert state.players[1].passed_win
    assert state.players[1].has_drawn_since_pass

    state.apply_action(
        1,
        Action(action_type=ActionType.DISCARD, tile_id=8),
        config=config,
    )
    assert not state.players[1].passed_win
    assert not state.players[1].has_drawn_since_pass


def test_pass_does_not_set_furiten_when_player_cannot_win():
    state = make_state(current_turn=1)
    state.players[1].hand.pop()
    state.players[1].hand.append(30)

    state.apply_action(1, Action(action_type=ActionType.PASS))

    assert not state.players[1].passed_win
    assert not state.players[1].has_drawn_since_pass


def test_non_strict_pass_rule_allows_win_after_passing():
    state = make_state(current_turn=1)
    config = RulesetConfig(
        rule_mechanics=RuleMechanics(strict_pass_rule=False),
    )
    win = Action(action_type=ActionType.WIN, tile_id=31)

    state.apply_action(1, Action(action_type=ActionType.PASS), config=config)

    assert not state.players[1].passed_win
    assert state.resolve_reaction_priority({1: win}, config=config) == {1: win}


@pytest.mark.parametrize(
    ("dealer_wins", "expected_dealer", "expected_streak"),
    [
        (True, 2, 5),
        (False, 3, 0),
    ],
)
def test_round_completion_updates_dealer_and_streak(
    dealer_wins,
    expected_dealer,
    expected_streak,
):
    state = make_state(dealer=2)
    state.lian_zhuang = 4

    state.complete_round(winner_id=2 if dealer_wins else 0)

    assert state.dealer == expected_dealer
    assert state.lian_zhuang == expected_streak
    assert state.is_over


@pytest.mark.parametrize("winner_id", [None, 2])
def test_draw_or_dealer_win_retains_dealer_and_increments_streak(winner_id):
    state = make_state(dealer=2)
    state.lian_zhuang = 6

    state.complete_round(winner_id=winner_id)

    assert state.dealer == 2
    assert state.lian_zhuang == 7
    assert state.is_over


def test_non_dealer_win_rotates_dealer_from_last_seat_to_zero():
    state = make_state(dealer=3)
    state.lian_zhuang = 2

    state.complete_round(winner_id=1)

    assert state.dealer == 0
    assert state.lian_zhuang == 0
    assert state.is_over


def test_round_completion_rejects_invalid_winner_without_changing_state():
    state = make_state(dealer=2)
    state.lian_zhuang = 3

    with pytest.raises(ValueError, match="Unknown winner seat"):
        state.complete_round(winner_id=4)

    assert state.dealer == 2
    assert state.lian_zhuang == 3
    assert not state.is_over


def test_multiple_ron_candidates_resolve_to_nearest_winner():
    state = make_state()
    reactions = {
        1: Action(action_type=ActionType.WIN, tile_id=31),
        2: Action(action_type=ActionType.WIN, tile_id=31),
        3: Action(action_type=ActionType.PONG, tile_id=31),
    }
    config = RulesetConfig(
        rule_mechanics=RuleMechanics(multi_winner=True),
    )

    assert state.resolve_reaction_priority(reactions, config=config) == {
        1: reactions[1],
    }


def test_multiple_ron_order_wraps_around_seat_zero():
    state = make_state()
    state.last_discard.player_id = 3
    reactions = {
        0: Action(action_type=ActionType.WIN, tile_id=31),
        2: Action(action_type=ActionType.WIN, tile_id=31),
    }

    assert state.resolve_reaction_priority(reactions) == {
        0: reactions[0],
    }


def test_wall_exhaustion_at_reserve_causes_draw_and_retains_dealer():
    state = make_state(dealer=2, current_turn=1, wall=[8] * 16)
    state.lian_zhuang = 1

    assert state.draw_tile() is None

    assert state.wall_count == 16
    assert len(state.wall) == 16
    assert state.is_over
    assert state.dealer == 2
    assert state.lian_zhuang == 2


def test_last_drawable_tile_is_drawn_before_next_attempt_ends_round():
    state = make_state(dealer=1, current_turn=0, wall=[8] * 17)
    state.lian_zhuang = 3
    config = RulesetConfig()

    action = state.draw_tile(config=config)

    assert action == Action(action_type=ActionType.DRAW_TILE, tile_id=8)
    assert len(state.wall) == state.wall_count == 16
    assert not state.is_over
    assert state.lian_zhuang == 3

    assert state.draw_tile(config=config) is None
    assert state.is_over
    assert state.dealer == 1
    assert state.lian_zhuang == 4


def test_repeated_wall_exhaustion_does_not_settle_round_twice():
    state = make_state(dealer=3, current_turn=1)
    state.lian_zhuang = 4

    assert state.draw_tile() is None
    assert state.draw_tile() is None

    assert state.is_over
    assert state.dealer == 3
    assert state.lian_zhuang == 5
