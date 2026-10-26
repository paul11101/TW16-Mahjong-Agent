from collections import Counter
from random import Random

import pytest

from src.common.schemas import ActionType
from src.rules.game_state import GameState, LastDiscard, Meld, PlayerState


def make_players():
    return {seat: PlayerState(seat_id=seat) for seat in range(4)}


def make_finished_round():
    players = make_players()
    players[0].score = 21500
    players[1].score = 18200
    players[2].score = 20700
    players[3].score = 19600
    players[0].hand = [0, 1, 2]
    players[0].discards = [3]
    players[0].melds = [
        Meld(meld_type=ActionType.PONG, tiles=[4, 4, 4], from_player=1)
    ]
    players[0].flowers = [34]
    players[0].passed_win = True
    players[0].has_drawn_since_pass = True
    players[0].is_tenpai = True
    players[0].is_menqing = False

    state = GameState(
        game_id="round-transition-test",
        dealer=0,
        lian_zhuang=2,
        current_turn=1,
        wall=[8] * 20,
        players=players,
        last_discard=LastDiscard(player_id=1, tile_id=5),
        pending_players=[0, 2],
    )
    state.complete_round(winner_id=1)
    return state


def test_next_round_clears_previous_round_and_preserves_scores():
    state = make_finished_round()
    expected_scores = {seat: player.score for seat, player in state.players.items()}

    state.next_round(rng=Random(42))

    assert state.is_over is False
    assert state.last_discard is None
    assert state.pending_players == []
    assert state.current_turn == state.dealer
    assert state.dealer == 1
    assert {seat: player.score for seat, player in state.players.items()} == expected_scores
    assert all(not player.discards for player in state.players.values())
    assert all(not player.melds for player in state.players.values())
    assert all(not player.passed_win for player in state.players.values())
    assert all(not player.has_drawn_since_pass for player in state.players.values())
    assert all(not player.is_tenpai and player.is_menqing for player in state.players.values())
    assert all(
        len(state.players[seat].hand) == (17 if seat == state.dealer else 16)
        for seat in range(4)
    )


def test_next_round_preserves_all_tiles_across_wall_hands_and_flowers():
    state = make_finished_round()
    state.next_round(rng=Random(19))

    dealt_tiles = Counter(
        tile
        for player in state.players.values()
        for tile in player.hand + player.flowers
    )
    assert dealt_tiles + Counter(state.wall) == Counter(
        [tile for tile in range(34) for _ in range(4)] + list(range(34, 42))
    )
    assert len(state.wall) + sum(
        len(player.hand) + len(player.flowers) for player in state.players.values()
    ) == 144
    assert state.wall_count == len(state.wall)


def test_reset_round_state_clears_player_zones_and_flags_without_changing_scores():
    state = make_finished_round()
    scores_before_reset = {seat: player.score for seat, player in state.players.items()}

    state.reset_round_state()

    assert {seat: player.score for seat, player in state.players.items()} == scores_before_reset
    assert all(
        not player.hand
        and not player.discards
        and not player.melds
        and not player.flowers
        and not player.passed_win
        and not player.has_drawn_since_pass
        and not player.is_tenpai
        and player.is_menqing
        for player in state.players.values()
    )
    assert state.wall == []
    assert state.wall_count == 0
    assert state.last_discard is None
    assert state.pending_players == []


def test_next_round_requires_completed_round():
    state = GameState(
        game_id="unfinished-round",
        players=make_players(),
    )

    with pytest.raises(ValueError, match="before the current round is completed"):
        state.next_round(rng=Random(1))


def test_draw_round_retains_dealer_and_starts_next_round():
    state = GameState(
        game_id="draw-round-transition-test",
        dealer=2,
        lian_zhuang=4,
        players=make_players(),
    )
    state.players[2].score = 21000
    state.complete_round()
    score_before = state.players[2].score

    state.next_round(rng=Random(7))

    assert state.dealer == 2
    assert state.lian_zhuang == 5
    assert state.current_turn == 2
    assert state.is_over is False
    assert state.players[2].score == score_before
