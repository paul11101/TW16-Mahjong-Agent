from src.common.schemas import ActionType
from src.rules.game_state import GameState, LastDiscard, PlayerState
from src.rules.rule import Action


def test_pong_claim_removes_two_tiles_and_discard():
    players = {seat: PlayerState(seat_id=seat) for seat in range(4)}
    players[0].discards = [27]
    players[1].hand = [27, 27, 8]
    state = GameState(
        game_id="pong-claim-test",
        current_turn=1,
        players=players,
        last_discard=LastDiscard(player_id=0, tile_id=27),
    )

    state.apply_action(1, Action(action_type=ActionType.PONG, tile_id=27))

    assert state.players[1].hand == [8]
    assert state.players[1].melds[0].meld_type == ActionType.PONG
    assert state.players[1].melds[0].tiles == [27, 27, 27]
    assert state.players[1].melds[0].from_player == 0
    assert state.players[0].discards == []
    assert state.last_discard is None
    assert state.current_turn == 1
