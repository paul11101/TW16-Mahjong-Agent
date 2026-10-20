from src.common.schemas import ActionType
from src.rules.game_state import GameState, LastDiscard, PlayerState
from src.rules.legal_actions import LegalActionGenerator
from src.rules.rule import Action


def test_chi_claim_removes_discard_and_keeps_claimant_turn():
    players = {seat: PlayerState(seat_id=seat) for seat in range(4)}
    players[0].discards = [2]
    players[1].hand = [0, 1, 8]
    state = GameState(
        game_id="chi-claim-test",
        current_turn=1,
        players=players,
        last_discard=LastDiscard(player_id=0, tile_id=2),
    )

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


def test_fixed_reaction_board_offers_chi_only_to_next_player():
    hand = [0, 1, 4, 5, 6, 9, 10, 11, 18, 19, 20, 27, 28, 29, 30, 31]
    generator = LegalActionGenerator()

    actions = generator.get_response_actions(
        hand=hand,
        target_tile=2,
        is_previous_player=True,
    )
    wrong_seat_actions = generator.get_response_actions(
        hand=hand,
        target_tile=2,
        is_previous_player=False,
    )

    assert {action.action_type for action in actions} == {
        ActionType.CHI,
        ActionType.PASS,
    }
    assert ActionType.CHI not in [action.action_type for action in wrong_seat_actions]
