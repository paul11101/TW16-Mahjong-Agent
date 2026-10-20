from src.common.schemas import ActionType
from src.rules.game_state import GameState, LastDiscard, PlayerState
from src.rules.legal_actions import LegalActionGenerator
from src.rules.rule import Action


def make_reaction_state(target_tile=2):
    players = {seat: PlayerState(seat_id=seat) for seat in range(4)}
    players[0].discards = [target_tile]
    return GameState(
        game_id="reaction-priority-test",
        players=players,
        last_discard=LastDiscard(player_id=0, tile_id=target_tile),
    )


def test_win_beats_pong_and_chi():
    state = make_reaction_state()
    reactions = {
        1: Action(action_type=ActionType.CHI, tile_id=2, sequence=[0, 1, 2]),
        2: Action(action_type=ActionType.PONG, tile_id=2),
        3: Action(action_type=ActionType.WIN, tile_id=2),
    }

    assert state.resolve_reaction_priority(reactions) == {3: reactions[3]}


def test_pong_beats_chi():
    state = make_reaction_state()
    reactions = {
        1: Action(action_type=ActionType.CHI, tile_id=2, sequence=[0, 1, 2]),
        2: Action(action_type=ActionType.PONG, tile_id=2),
    }

    assert state.resolve_reaction_priority(reactions) == {2: reactions[2]}


def test_exposed_kong_beats_chi():
    state = make_reaction_state()
    reactions = {
        1: Action(action_type=ActionType.CHI, tile_id=2, sequence=[0, 1, 2]),
        2: Action(action_type=ActionType.KONG, tile_id=2, kong_type="ming"),
    }

    assert state.resolve_reaction_priority(reactions) == {2: reactions[2]}


def test_equal_priority_reactions_use_nearest_seat():
    state = make_reaction_state()
    reactions = {
        1: Action(action_type=ActionType.PONG, tile_id=2),
        2: Action(action_type=ActionType.KONG, tile_id=2, kong_type="ming"),
    }

    assert state.resolve_reaction_priority(reactions) == {1: reactions[1]}


def test_only_pass_is_generated_when_no_reaction_is_available():
    actions = LegalActionGenerator().get_response_actions(
        hand=[0, 3, 5, 8, 10, 12, 15, 17, 19, 21, 23, 27, 29, 31, 32, 33],
        target_tile=20,
        is_previous_player=False,
    )

    assert [action.action_type for action in actions] == [ActionType.PASS]


def test_self_draw_turn_offers_win_and_discard():
    actions = LegalActionGenerator().get_turn_player_actions(
        hand=[0, 1, 2, 9, 10, 11, 18, 19, 20, 27, 27, 27, 28, 28, 28, 31, 31],
        last_drawn_tile=31,
        can_win_self_draw=True,
    )

    assert {action.action_type for action in actions} == {
        ActionType.WIN,
        ActionType.DISCARD,
    }
