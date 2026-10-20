import pytest

from src.common.schemas import ActionType
from src.rules.game_state import GameState, LastDiscard, PlayerState
from src.rules.legal_actions import LegalActionGenerator
from src.rules.rule import Action, RuleMechanics, RulesetConfig


def make_players():
    return {seat: PlayerState(seat_id=seat) for seat in range(4)}


def make_claim_state(target_tile, claimant_hand):
    players = make_players()
    players[0].discards = [target_tile]
    players[1].hand = claimant_hand
    return GameState(
        game_id="meld-test",
        current_turn=1,
        players=players,
        wall=[9],
        last_discard=LastDiscard(player_id=0, tile_id=target_tile),
    )


def make_reaction_priority_state(target_tile=2):
    players = make_players()
    players[0].discards = [target_tile]
    return GameState(
        game_id="reaction-priority-test",
        players=players,
        last_discard=LastDiscard(player_id=0, tile_id=target_tile),
    )


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


def test_chi_claim_removes_discard_and_keeps_claimant_turn():
    state = make_claim_state(2, [0, 1, 8])

    state.apply_action(
        1,
        Action(action_type=ActionType.CHI, tile_id=2, sequence=[0, 1, 2]),
    )

    meld = state.players[1].melds[0]
    assert state.players[1].hand == [8]
    assert meld.meld_type == ActionType.CHI
    assert meld.tiles == [0, 1, 2]
    assert meld.from_player == 0
    assert not state.players[1].is_menqing
    assert state.players[0].discards == []
    assert state.last_discard is None
    assert state.current_turn == 1


def test_pong_claim_removes_two_tiles_and_discard():
    state = make_claim_state(27, [27, 27, 8])

    state.apply_action(1, Action(action_type=ActionType.PONG, tile_id=27))

    assert state.players[1].hand == [8]
    assert state.players[1].melds[0].meld_type == ActionType.PONG
    assert state.players[1].melds[0].tiles == [27, 27, 27]
    assert state.players[0].discards == []
    assert state.current_turn == 1


def test_reaction_priority_win_beats_pong_and_chi():
    state = make_reaction_priority_state()
    reactions = {
        1: Action(action_type=ActionType.CHI, tile_id=2, sequence=[0, 1, 2]),
        2: Action(action_type=ActionType.PONG, tile_id=2),
        3: Action(action_type=ActionType.WIN, tile_id=2),
    }

    assert state.resolve_reaction_priority(reactions) == {3: reactions[3]}


def test_reaction_priority_pong_beats_chi():
    state = make_reaction_priority_state()
    reactions = {
        1: Action(action_type=ActionType.CHI, tile_id=2, sequence=[0, 1, 2]),
        2: Action(action_type=ActionType.PONG, tile_id=2),
    }

    assert state.resolve_reaction_priority(reactions) == {2: reactions[2]}


def test_reaction_priority_exposed_kong_beats_chi():
    state = make_reaction_priority_state()
    reactions = {
        1: Action(action_type=ActionType.CHI, tile_id=2, sequence=[0, 1, 2]),
        2: Action(action_type=ActionType.KONG, tile_id=2, kong_type="ming"),
    }

    assert state.resolve_reaction_priority(reactions) == {2: reactions[2]}


def test_equal_priority_reactions_use_nearest_seat():
    state = make_reaction_priority_state()
    reactions = {
        1: Action(action_type=ActionType.PONG, tile_id=2),
        2: Action(action_type=ActionType.KONG, tile_id=2, kong_type="ming"),
    }

    assert state.resolve_reaction_priority(reactions) == {1: reactions[1]}


def test_exposed_kong_claims_discard_and_draws_replacement():
    state = make_claim_state(27, [27, 27, 27, 8])

    replacement = state.apply_action(
        1,
        Action(action_type=ActionType.KONG, tile_id=27, kong_type="ming"),
        config=RulesetConfig(
            rule_mechanics=RuleMechanics(reserved_wall_tiles=0),
        ),
    )

    assert replacement == Action(action_type=ActionType.DRAW_TILE, tile_id=9)
    assert state.players[1].hand == [8, 9]
    assert state.players[1].melds[0].meld_type == ActionType.KONG
    assert state.players[1].melds[0].tiles == [27, 27, 27, 27]
    assert state.players[1].melds[0].kong_type == "ming"
    assert state.players[0].discards == []
    assert state.current_turn == 1
    assert state.wall_count == 0


def test_concealed_kong_preserves_menqing_and_draws_replacement():
    state = GameState(
        game_id="concealed-kong-test",
        players={
            0: PlayerState(seat_id=0, hand=[31, 31, 31, 31, 8]),
            **{seat: PlayerState(seat_id=seat) for seat in range(1, 4)},
        },
        wall=[9],
    )

    replacement = state.apply_action(
        0,
        Action(action_type=ActionType.KONG, tile_id=31, kong_type="an"),
        config=RulesetConfig(
            rule_mechanics=RuleMechanics(reserved_wall_tiles=0),
        ),
    )

    assert replacement == Action(action_type=ActionType.DRAW_TILE, tile_id=9)
    assert state.players[0].hand == [8, 9]
    assert state.players[0].melds[0].tiles == [31, 31, 31, 31]
    assert state.players[0].melds[0].kong_type == "an"
    assert state.players[0].melds[0].from_player == 0
    assert state.players[0].is_menqing
    assert state.wall_count == 0


def test_added_kong_upgrades_existing_pong_and_draws_replacement():
    state = GameState(
        game_id="added-kong-test",
        players={
            0: PlayerState(
                seat_id=0,
                hand=[31, 8],
                melds=[{
                    "meld_type": ActionType.PONG,
                    "tiles": [31, 31, 31],
                    "from_player": 2,
                }],
            ),
            **{seat: PlayerState(seat_id=seat) for seat in range(1, 4)},
        },
        wall=[9],
    )

    replacement = state.apply_action(
        0,
        Action(action_type=ActionType.KONG, tile_id=31, kong_type="jia"),
        config=RulesetConfig(
            rule_mechanics=RuleMechanics(reserved_wall_tiles=0),
        ),
    )

    assert replacement == Action(action_type=ActionType.DRAW_TILE, tile_id=9)
    assert state.players[0].hand == [8, 9]
    assert len(state.players[0].melds) == 1
    assert state.players[0].melds[0].tiles == [31, 31, 31, 31]
    assert state.players[0].melds[0].kong_type == "jia"
    assert state.players[0].melds[0].from_player == 2
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


@pytest.mark.parametrize(
    ("hand", "target", "previous", "expected"),
    [
        ([27, 27, 27, 0, 0, 1, 2, 9, 10, 11, 18, 19, 20, 28, 29, 30],
         27, False, {ActionType.KONG, ActionType.PONG, ActionType.PASS}),
        ([0, 1, 4, 5, 6, 9, 10, 11, 18, 19, 20, 27, 28, 29, 30, 31],
         2, True, {ActionType.CHI, ActionType.PASS}),
        ([0, 3, 5, 8, 10, 12, 15, 17, 19, 21, 23, 27, 29, 31, 32, 33],
         20, False, {ActionType.PASS}),
    ],
)
def test_fixed_reaction_boards(hand, target, previous, expected):
    actions = LegalActionGenerator().get_response_actions(
        hand=hand,
        target_tile=target,
        is_previous_player=previous,
    )

    assert {action.action_type for action in actions} == expected


def test_fixed_turn_board_offers_self_draw_and_discard():
    hand = [0, 1, 2, 9, 10, 11, 18, 19, 20, 27, 27, 27, 28, 28, 28, 31, 31]
    actions = LegalActionGenerator().get_turn_player_actions(
        hand=hand,
        last_drawn_tile=31,
        can_win_self_draw=True,
    )

    assert {action.action_type for action in actions} == {
        ActionType.WIN,
        ActionType.DISCARD,
    }


def test_fixed_turn_board_offers_concealed_and_added_kong():
    hand = [5, 5, 5, 5, 10, 10, 18, 19, 20, 27, 28, 29, 30, 31, 32, 33, 10]
    actions = LegalActionGenerator().get_turn_player_actions(
        hand=hand,
        last_drawn_tile=10,
        melded_pongs=[10],
    )

    assert ActionType.KONG in [action.action_type for action in actions]
    assert ActionType.DISCARD in [action.action_type for action in actions]


def test_fixed_draw_boards_distinguish_flower_from_normal_tile():
    generator = LegalActionGenerator()

    assert generator.get_draw_actions(35).action_type == ActionType.FLOWER_REPLACEMENT
    assert generator.get_draw_actions(8).action_type == ActionType.DRAW_TILE
