from src.common.schemas import ActionType
from src.rules.game_state import GameState, LastDiscard, PlayerState
from src.rules.legal_actions import LegalActionGenerator
from src.rules.rule import Action, RuleMechanics, RulesetConfig


def make_claim_state(target_tile, claimant_hand):
    players = {seat: PlayerState(seat_id=seat) for seat in range(4)}
    players[0].discards = [target_tile]
    players[1].hand = claimant_hand
    return GameState(
        game_id="kong-claim-test",
        current_turn=1,
        players=players,
        wall=[9],
        last_discard=LastDiscard(player_id=0, tile_id=target_tile),
    )


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
    players = {
        0: PlayerState(seat_id=0, hand=[31, 31, 31, 31, 8]),
        **{seat: PlayerState(seat_id=seat) for seat in range(1, 4)},
    }
    state = GameState(
        game_id="concealed-kong-test",
        players=players,
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
    players = {
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
    }
    state = GameState(
        game_id="added-kong-test",
        players=players,
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


def test_fixed_reaction_board_offers_exposed_kong_and_pong():
    actions = LegalActionGenerator().get_response_actions(
        hand=[27, 27, 27, 0, 0, 1, 2, 9, 10, 11, 18, 19, 20, 28, 29, 30],
        target_tile=27,
        is_previous_player=False,
    )

    assert {action.action_type for action in actions} == {
        ActionType.KONG,
        ActionType.PONG,
        ActionType.PASS,
    }


def test_turn_actions_include_concealed_and_added_kongs():
    actions = LegalActionGenerator().get_turn_player_actions(
        hand=[5, 5, 5, 5, 10, 10, 18, 19, 20, 27, 28, 29, 30, 31, 32, 33, 10],
        last_drawn_tile=10,
        melded_pongs=[10],
    )
    kong_actions = [action for action in actions if action.action_type == ActionType.KONG]

    assert {(action.tile_id, action.kong_type) for action in kong_actions} == {
        (5, "an"),
        (10, "jia"),
    }
