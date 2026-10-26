from collections import Counter
from random import Random

import pytest

from src.common.schemas import ActionType
from src.rules.fan_calculator import FanCalculator
from src.rules.game_state import GameState, PlayerState, is_basic_win
from src.rules.legal_actions import LegalActionGenerator
from src.rules.rule import RulesetConfig
from src.rules.settlement_calculator import SettlementCalculator
from src.rules.state_machine import GameStage, MahjongStateMachine


INITIAL_TILE_COUNTS = Counter(
    [tile for tile in range(34) for _ in range(4)] + list(range(34, 42))
)


def assert_round_invariants(state: GameState, expected_score_total: int) -> None:
    located_tiles = Counter(state.wall)
    for player in state.players.values():
        located_tiles.update(player.hand)
        located_tiles.update(player.discards)
        located_tiles.update(player.flowers)
        for meld in player.melds:
            located_tiles.update(meld.tiles)

    assert len(state.wall) + sum(
        len(player.hand)
        + len(player.discards)
        + len(player.flowers)
        + sum(len(meld.tiles) for meld in player.melds)
        for player in state.players.values()
    ) == 144
    assert located_tiles == INITIAL_TILE_COUNTS
    assert state.wall_count == len(state.wall)
    assert sum(player.score for player in state.players.values()) == expected_score_total


def assert_clean_new_round(state: GameState, expected_score_total: int) -> None:
    assert all(
        not player.passed_win
        and not player.has_drawn_since_pass
        and not player.is_tenpai
        and player.is_menqing
        and not player.melds
        and not player.discards
        for player in state.players.values()
    )
    assert_round_invariants(state, expected_score_total)


def choose_random_action(actions, rng: Random):
    return rng.choice(actions)


def run_simulated_round(
    machine: MahjongStateMachine,
    rng: Random,
    config: RulesetConfig,
    expected_score_total: int,
) -> str:
    state = machine.state
    action_generator = LegalActionGenerator(config)
    try:
        if machine.stage == GameStage.INIT_ROUND:
            machine.start_round()
        elif machine.stage != GameStage.PLAYER_TURN:
            raise AssertionError(f"Unexpected stage at round start: {machine.stage}")
        assert_round_invariants(state, expected_score_total)
        pending_drawn_tile = None
        for _ in range(200):
            player_id = state.current_turn
            player = state.players[player_id]
            standing_hand_size = config.hand_size - 3 * len(player.melds)
            last_drawn_tile = pending_drawn_tile
            pending_drawn_tile = None

            if len(player.hand) == standing_hand_size and last_drawn_tile is None:
                draw_action = state.draw_tile(config=config)
                assert_round_invariants(state, expected_score_total)
                if state.is_over:
                    machine.begin_settlement()
                    machine.process_round_end(is_draw=True)
                    assert_clean_new_round(state, expected_score_total)
                    return "draw"
                assert draw_action is not None
                last_drawn_tile = draw_action.tile_id

            melded_pongs = [
                meld.tiles[0]
                for meld in player.melds
                if meld.meld_type == ActionType.PONG
            ]
            actions = action_generator.get_turn_player_actions(
                hand=player.hand,
                last_drawn_tile=last_drawn_tile,
                melded_pongs=melded_pongs,
                can_win_self_draw=state.is_basic_win(player_id),
            )
            action = choose_random_action(actions, rng)
            if action.action_type == ActionType.WIN:
                fans, _ = FanCalculator().calculate(
                    player.hand,
                    winner_seat=player_id,
                    dealer_seat=state.dealer,
                    lian_zhuang=state.lian_zhuang,
                    is_self_draw=True,
                    melds=player.melds,
                    flowers=player.flowers,
                    config=config,
                )
                scores = SettlementCalculator().settle(
                    {seat: current.score for seat, current in state.players.items()},
                    winner_seat=player_id,
                    total_fans=fans,
                    is_self_draw=True,
                )
                for seat, score in scores.items():
                    state.players[seat].score = score
                assert_round_invariants(state, expected_score_total)
                machine.begin_settlement()
                machine.process_round_end(
                    winner_seats=[player_id],
                    is_draw=False,
                )
                assert_clean_new_round(state, expected_score_total)
                return "win"

            draw_action = state.apply_action(player_id, action, config=config)
            assert_round_invariants(state, expected_score_total)
            if state.is_over:
                machine.begin_settlement()
                machine.process_round_end(is_draw=True)
                assert_clean_new_round(state, expected_score_total)
                return "draw"
            if action.action_type == ActionType.KONG:
                assert draw_action is not None
                pending_drawn_tile = draw_action.tile_id
                continue
            discard = state.last_discard
            assert discard is not None
            machine.begin_claim_phase()

            reactions = {}
            for reacting_seat, reacting_player in state.players.items():
                if reacting_seat == player_id:
                    continue
                can_win = is_basic_win(
                    reacting_player.hand + [discard.tile_id],
                    meld_count=len(reacting_player.melds),
                )
                options = action_generator.get_response_actions(
                    hand=reacting_player.hand,
                    target_tile=discard.tile_id,
                    is_previous_player=reacting_seat == (player_id + 1) % 4,
                    can_win_honin=can_win,
                    passed_win=reacting_player.passed_win,
                )
                options = [
                    option
                    for option in options
                    if option.action_type
                    in (
                        ActionType.PASS,
                        ActionType.CHI,
                        ActionType.PONG,
                        ActionType.KONG,
                        ActionType.WIN,
                    )
                ]
                chosen = choose_random_action(options, rng)
                if chosen.action_type == ActionType.PASS:
                    state.apply_action(reacting_seat, chosen, config=config)
                else:
                    reactions[reacting_seat] = chosen
                assert_round_invariants(state, expected_score_total)

            resolved = state.resolve_reaction_priority(reactions, config=config)
            if not resolved:
                machine.resume_player_turn()
                continue

            reacting_seat, reaction = next(iter(resolved.items()))
            if reaction.action_type == ActionType.WIN:
                fans, _ = FanCalculator().calculate(
                    state.players[reacting_seat].hand + [discard.tile_id],
                    winner_seat=reacting_seat,
                    dealer_seat=state.dealer,
                    lian_zhuang=state.lian_zhuang,
                    melds=state.players[reacting_seat].melds,
                    flowers=state.players[reacting_seat].flowers,
                    config=config,
                )
                scores = SettlementCalculator().settle(
                    {seat: current.score for seat, current in state.players.items()},
                    winner_seat=reacting_seat,
                    total_fans=fans,
                    is_self_draw=False,
                    loser_seat=player_id,
                )
                for seat, score in scores.items():
                    state.players[seat].score = score
                assert_round_invariants(state, expected_score_total)
                machine.begin_settlement()
                machine.process_round_end(
                    winner_seats=[reacting_seat],
                    is_draw=False,
                )
                assert_clean_new_round(state, expected_score_total)
                return "win"

            draw_action = state.apply_action(reacting_seat, reaction, config=config)
            assert_round_invariants(state, expected_score_total)
            machine.resume_player_turn()
            if reaction.action_type == ActionType.KONG:
                if state.is_over:
                    machine.begin_settlement()
                    machine.process_round_end(is_draw=True)
                    assert_clean_new_round(state, expected_score_total)
                    return "draw"
                assert draw_action is not None
                pending_drawn_tile = draw_action.tile_id

        raise AssertionError("Round exceeded the 200-turn safety limit")
    except Exception as error:
        debug_state = state.model_dump_json(indent=2)
        pytest.fail(
            f"Simulation failed at stage={machine.stage.value}, "
            f"round_wind={state.round_wind}, dealer={state.dealer}, "
            f"turn={state.current_turn}: {error}\nGameState:\n{debug_state}",
            pytrace=True,
        )


def run_continuous_game(seed: int, round_count: int) -> list[str]:
    rng = Random(seed)
    state = GameState(
        game_id=f"full-game-{seed}",
        players={seat: PlayerState(seat_id=seat) for seat in range(4)},
    )
    config = RulesetConfig()
    machine = MahjongStateMachine(state, config=config, rng=rng)
    initial_score_total = sum(player.score for player in state.players.values())
    outcomes = []

    for _ in range(round_count):
        assert machine.stage in (GameStage.INIT_ROUND, GameStage.PLAYER_TURN)
        outcomes.append(
            run_simulated_round(machine, rng, config, initial_score_total)
        )
        assert machine.stage == GameStage.PLAYER_TURN

    return outcomes


def test_continuous_rounds_simulation():
    outcomes = run_continuous_game(seed=20261027, round_count=12)

    assert len(outcomes) == 12
    assert set(outcomes) <= {"win", "draw"}


def test_game_invariants_during_execution():
    outcomes = run_continuous_game(seed=19, round_count=10)

    assert len(outcomes) == 10


def test_wall_exhaustion_completed_by_game_state_starts_next_round_once():
    rng = Random(71)
    state = GameState(
        game_id="wall-exhaustion-transition",
        players={seat: PlayerState(seat_id=seat) for seat in range(4)},
    )
    machine = MahjongStateMachine(state, rng=rng)
    machine.start_round()

    state.wall = state.wall[:16]
    state.wall_count = len(state.wall)
    dealer_before = state.dealer
    streak_before = state.lian_zhuang

    assert state.draw_tile() is None
    assert state.is_over
    assert state.dealer == dealer_before
    assert state.lian_zhuang == streak_before + 1

    machine.begin_settlement()
    machine.process_round_end(is_draw=True)

    assert machine.stage == GameStage.PLAYER_TURN
    assert state.is_over is False
    assert state.dealer == dealer_before
    assert state.lian_zhuang == streak_before + 1
