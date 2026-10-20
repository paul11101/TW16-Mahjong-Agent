import pytest

from src.common.schemas import ActionType
from src.rules.game_state import GameState, LastDiscard, PlayerState, is_basic_win
from src.rules.legal_actions import LegalActionGenerator
from src.rules.rule import Action, RuleMechanics, RulesetConfig


def make_players():
    return {seat: PlayerState(seat_id=seat) for seat in range(4)}


def make_passed_win_state(*, wall=None, discard_tile=31):
    players = make_players()
    players[0].discards = [discard_tile]
    players[1].hand = [
        0, 1, 2,
        3, 4, 5,
        9, 10, 11,
        18, 19, 20,
        27, 27, 27,
        discard_tile,
    ]
    return GameState(
        game_id="w5-passed-win-test",
        current_turn=1,
        players=players,
        wall=[] if wall is None else wall,
        last_discard=LastDiscard(player_id=0, tile_id=discard_tile),
    )


def test_passed_ron_blocks_win_until_draw_then_nonwinning_discard():
    state = make_passed_win_state(wall=[8])
    config = RulesetConfig(
        rule_mechanics=RuleMechanics(reserved_wall_tiles=0),
    )
    win = Action(action_type=ActionType.WIN, tile_id=31)

    assert is_basic_win(
        state.players[1].hand + [state.last_discard.tile_id],
        meld_count=len(state.players[1].melds),
    )
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
        27, 27, 27,
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

    assert is_basic_win(state.players[0].hand)
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
