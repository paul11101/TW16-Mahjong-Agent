import pytest

from src.common.schemas import ActionType
from src.rules.game_state import GameState, LastDiscard, PlayerState
from src.rules.legal_actions import LegalActionGenerator
from src.rules.rule import Action, RuleMechanics, RulesetConfig


def make_players():
    return {seat: PlayerState(seat_id=seat) for seat in range(4)}


def make_passed_win_state(*, current_turn=1, wall=None, discard_tile=31):
    players = make_players()
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
        game_id="w5-passed-win-test",
        current_turn=current_turn,
        players=players,
        wall=[] if wall is None else wall,
        last_discard=LastDiscard(player_id=0, tile_id=discard_tile),
    )


def make_reaction_state(target_tile=2):
    players = make_players()
    players[0].discards = [target_tile]
    return GameState(
        game_id="w5-reaction-test",
        players=players,
        last_discard=LastDiscard(player_id=0, tile_id=target_tile),
    )


def test_passed_ron_blocks_win_until_draw_then_nonwinning_discard():
    state = make_passed_win_state(wall=[8])
    config = RulesetConfig(
        rule_mechanics=RuleMechanics(reserved_wall_tiles=0),
    )
    win = Action(action_type=ActionType.WIN, tile_id=31)

    state.apply_action(1, Action(action_type=ActionType.PASS), config=config)
    assert state.players[1].passed_win
    assert not state.players[1].has_drawn_since_pass

    with pytest.raises(ValueError, match="False win"):
        state.resolve_reaction_priority({1: win}, config=config)

    for target_tile in (31, 30):
        actions = LegalActionGenerator().get_response_actions(
            hand=state.players[1].hand,
            target_tile=target_tile,
            is_previous_player=False,
            can_win_honin=True,
            passed_win=state.players[1].passed_win,
        )
        assert ActionType.WIN not in [action.action_type for action in actions]

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


def test_pass_does_not_set_furiten_when_hand_cannot_win():
    state = make_passed_win_state()
    state.players[1].hand[-1] = 30

    state.apply_action(1, Action(action_type=ActionType.PASS))

    assert not state.players[1].passed_win
    assert not state.players[1].has_drawn_since_pass


def test_non_strict_pass_rule_allows_ron_after_pass():
    state = make_passed_win_state()
    config = RulesetConfig(
        rule_mechanics=RuleMechanics(strict_pass_rule=False),
    )
    win = Action(action_type=ActionType.WIN, tile_id=31)

    state.apply_action(1, Action(action_type=ActionType.PASS), config=config)

    assert not state.players[1].passed_win
    assert state.resolve_reaction_priority({1: win}, config=config) == {1: win}


def test_self_draw_pass_furiten_clears_after_draw_and_nonwinning_discard():
    players = make_players()
    players[0].hand = [
        0, 1, 2,
        3, 4, 5,
        9, 10, 11,
        18, 19, 20,
        27, 28, 29,
        31, 31,
    ]
    state = GameState(
        game_id="w5-self-draw-furiten-test",
        current_turn=0,
        wall=[8],
        players=players,
    )
    config = RulesetConfig(
        rule_mechanics=RuleMechanics(reserved_wall_tiles=0),
    )

    state.apply_action(0, Action(action_type=ActionType.DISCARD, tile_id=31))
    assert state.players[0].passed_win
    assert not state.players[0].has_drawn_since_pass

    state.current_turn = 0
    state.draw_tile(player_id=0, config=config)
    assert state.players[0].passed_win
    assert state.players[0].has_drawn_since_pass

    state.apply_action(
        0,
        Action(action_type=ActionType.DISCARD, tile_id=8),
        config=config,
    )
    assert not state.players[0].passed_win
    assert not state.players[0].has_drawn_since_pass


@pytest.mark.parametrize("winner_id", [None, 2])
def test_draw_or_dealer_win_retains_dealer_and_increments_streak(winner_id):
    state = GameState(
        game_id="w5-dealer-retains-test",
        dealer=2,
        lian_zhuang=6,
        players=make_players(),
    )

    state.complete_round(winner_id=winner_id)

    assert state.dealer == 2
    assert state.lian_zhuang == 7
    assert state.is_over


def test_non_dealer_win_rotates_dealer_and_clears_streak():
    state = GameState(
        game_id="w5-dealer-rotates-test",
        dealer=2,
        lian_zhuang=3,
        players=make_players(),
    )

    state.complete_round(winner_id=0)

    assert state.dealer == 3
    assert state.lian_zhuang == 0
    assert state.is_over


def test_invalid_winner_does_not_change_dealer_or_streak():
    state = GameState(
        game_id="w5-invalid-winner-test",
        dealer=2,
        lian_zhuang=3,
        players=make_players(),
    )

    with pytest.raises(ValueError, match="Unknown winner seat"):
        state.complete_round(winner_id=4)

    assert state.dealer == 2
    assert state.lian_zhuang == 3
    assert not state.is_over


def test_completed_round_cannot_increment_streak_twice():
    state = GameState(
        game_id="w5-complete-round-once-test",
        players=make_players(),
    )
    state.complete_round()

    with pytest.raises(ValueError, match="already been completed"):
        state.complete_round()

    assert state.lian_zhuang == 1


def test_dealer_rotation_wraps_from_seat_three_to_zero():
    state = GameState(
        game_id="w5-dealer-wraparound-test",
        dealer=3,
        lian_zhuang=4,
        players=make_players(),
    )

    state.complete_round(winner_id=0)

    assert state.dealer == 0
    assert state.lian_zhuang == 0
    assert state.is_over


def test_multiple_ron_candidates_choose_nearest_winner():
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


def test_wall_at_reserved_limit_causes_draw_and_dealer_retention():
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
    players = make_players()
    state = GameState(
        game_id="w5-flower-wall-exhaustion-test",
        players=players,
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
