from collections import Counter
from random import Random

import pytest

from src.common.schemas import ActionType
from src.rules.game_state import GameState, LastDiscard, Meld, PlayerState
from src.rules.rule import Action, RuleMechanics, RulesetConfig


FULL_TILE_SET = Counter(
    [tile_id for tile_id in range(34) for _ in range(4)] + list(range(34, 42))
)
NO_RESERVED_WALL = RulesetConfig(
    rule_mechanics=RuleMechanics(reserved_wall_tiles=0)
)


def assert_card_conservation(state):
    """Verify every physical tile is in exactly one active tile zone."""
    zones = Counter(state.wall)
    for player in state.players.values():
        zones.update(player.hand)
        zones.update(player.discards)
        zones.update(player.flowers)
        for meld in player.melds:
            zones.update(meld.tiles)

    assert zones == FULL_TILE_SET
    assert state.wall_count == len(state.wall)


def make_state(*, hands=None, discards=None, current_turn=0, draw_tile=None):
    hands = hands or {}
    discards = discards or {}
    players = {
        seat: PlayerState(
            seat_id=seat,
            hand=list(hands.get(seat, [])),
            discards=list(discards.get(seat, [])),
        )
        for seat in range(4)
    }

    known_tiles = Counter(
        tile_id
        for player in players.values()
        for tile_id in player.hand + player.discards
    )
    assert not (known_tiles - FULL_TILE_SET)
    remaining = FULL_TILE_SET - known_tiles

    wall = list(remaining.elements())
    if draw_tile is not None:
        wall.remove(draw_tile)
        wall.append(draw_tile)

    return GameState(
        game_id="card-conservation-test",
        current_turn=current_turn,
        wall=wall,
        wall_count=len(wall),
        players=players,
    )


def test_conservation_after_deal_and_regular_draw_discard():
    state = GameState(
        game_id="card-conservation-deal",
        players={seat: PlayerState(seat_id=seat) for seat in range(4)},
    )

    state.init_next_round(rng=Random(16))
    assert_card_conservation(state)
    assert len(state.players[state.dealer].hand) == 17
    assert all(
        len(player.hand) == 16
        for seat, player in state.players.items()
        if seat != state.dealer
    )

    drawn = state.draw_tile(config=NO_RESERVED_WALL)
    assert drawn is not None
    assert_card_conservation(state)

    state.apply_action(
        state.current_turn,
        Action(action_type=ActionType.DISCARD, tile_id=drawn.tile_id),
        config=NO_RESERVED_WALL,
    )
    assert_card_conservation(state)


@pytest.mark.parametrize(
    "action, target_tile, claimant_hand",
    [
        (Action(action_type=ActionType.CHI, tile_id=2, sequence=[0, 1, 2]), 2, [0, 1]),
        (Action(action_type=ActionType.PONG, tile_id=27), 27, [27, 27]),
    ],
)
def test_conservation_after_chi_or_pong_claim(action, target_tile, claimant_hand):
    state = make_state(
        hands={1: claimant_hand},
        discards={0: [target_tile]},
        current_turn=1,
    )
    state.last_discard = LastDiscard(player_id=0, tile_id=target_tile)
    assert_card_conservation(state)

    state.apply_action(1, action, config=NO_RESERVED_WALL)

    assert_card_conservation(state)
    assert state.players[0].discards == []
    assert state.players[1].melds[0].meld_type == action.action_type


def test_conservation_after_exposed_kong_and_replacement_draw():
    state = make_state(
        hands={1: [27, 27, 27]},
        discards={0: [27]},
        current_turn=1,
        draw_tile=8,
    )
    state.last_discard = LastDiscard(player_id=0, tile_id=27)
    assert_card_conservation(state)

    replacement = state.apply_action(
        1,
        Action(action_type=ActionType.KONG, tile_id=27, kong_type="ming"),
        config=NO_RESERVED_WALL,
    )

    assert replacement == Action(action_type=ActionType.DRAW_TILE, tile_id=8)
    assert state.players[1].melds[0].tiles == [27, 27, 27, 27]
    assert_card_conservation(state)


def test_conservation_after_flower_draw_and_replacement():
    state = make_state(current_turn=0, draw_tile=8)
    state.wall.remove(34)
    state.wall.remove(8)
    state.wall.extend([8, 34])
    state.wall_count = len(state.wall)
    assert_card_conservation(state)

    action = state.draw_tile(config=NO_RESERVED_WALL)

    assert action == Action(action_type=ActionType.DRAW_TILE, tile_id=8)
    assert state.players[0].flowers == [34]
    assert state.players[0].hand == [8]
    assert_card_conservation(state)
