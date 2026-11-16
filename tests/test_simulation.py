import traceback
from contextlib import contextmanager, nullcontext
import gc
import os
import sys
from random import Random
import tracemalloc
import pytest

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from src.common.schemas import ActionType
from src.rules.game_state import GameState, PlayerState, create_shuffled_wall, is_basic_win
from src.rules.legal_actions import LegalActionGenerator
from src.rules.rule import RuleMechanics, RulesetConfig
from src.strategy.adapters import actions_to_legal_actions, game_state_to_observation
from src.strategy.baseline import BaselinePolicy
from src.strategy.shanten import Taiwan16ShantenCalculator

@contextmanager
def log_simulation_errors(log_file):
    try:
        yield
    except Exception:
        log_file.write(f"ERROR\n{traceback.format_exc()}\n")
        log_file.flush()
        raise


@contextmanager
def bounded_python_memory_growth(max_growth_bytes=64 * 1024 * 1024):
    tracing_was_active = tracemalloc.is_tracing()
    if not tracing_was_active:
        tracemalloc.start()
    gc.collect()
    baseline, _ = tracemalloc.get_traced_memory()
    report = {"baseline_bytes": baseline}
    try:
        yield report
    finally:
        gc.collect()
        current, _ = tracemalloc.get_traced_memory()
        report["current_bytes"] = current
        report["growth_bytes"] = current - baseline
        report["max_growth_bytes"] = max_growth_bytes
        if not tracing_was_active:
            tracemalloc.stop()


def test_bounded_python_memory_growth_reports_final_measurement():
    tracing_was_active = tracemalloc.is_tracing()

    with bounded_python_memory_growth() as report:
        retained_allocation = bytearray(1024)

    assert report["growth_bytes"] >= 1024
    assert report["current_bytes"] - report["baseline_bytes"] == report["growth_bytes"]
    assert report["max_growth_bytes"] == 64 * 1024 * 1024
    assert tracemalloc.is_tracing() is tracing_was_active
    del retained_allocation


def assert_card_conservation(state, *, game_number, phase):
    state.assert_card_conservation(
        phase=f"simulation game {game_number}: {phase}"
    )


def preferred_reaction(actions):
    """Select each player's strongest available response before arbitration."""
    priorities = {
        ActionType.CHI: 1,
        ActionType.PONG: 2,
        ActionType.KONG: 2,
        ActionType.WIN: 3,
    }
    candidates = [action for action in actions if action.action_type in priorities]
    if not candidates:
        return None
    return max(candidates, key=lambda action: priorities[action.action_type])


@pytest.mark.slow
def test_random_games_complete_without_unexpected_exceptions():
    try:
        games_to_run = int(os.environ.get("MAHJONG_SIMULATION_GAMES", "1000"))
    except ValueError as error:
        raise ValueError("MAHJONG_SIMULATION_GAMES must be a positive integer") from error
    if games_to_run < 1:
        raise ValueError("MAHJONG_SIMULATION_GAMES must be a positive integer")
    default_memory_check = "1" if games_to_run >= 10_000 else "0"
    check_memory = os.environ.get(
        "MAHJONG_SIMULATION_CHECK_MEMORY",
        default_memory_check,
    )
    if check_memory not in ("0", "1"):
        raise ValueError("MAHJONG_SIMULATION_CHECK_MEMORY must be 0 or 1")

    config = RulesetConfig(
        rule_mechanics=RuleMechanics(
            strict_pass_rule=True,
            reserved_wall_tiles=16,
        ),
    )
    action_generator = LegalActionGenerator(config)
    policy = BaselinePolicy(calculator=Taiwan16ShantenCalculator())
    completed_games = 0
    wins = 0
    draws = 0
    total_steps = 0
    policy_decisions = 0
    reaction_checks = 0
    reaction_opportunities = 0
    reaction_actions = 0
    contested_reactions = 0
    resolved_reactions = 0
    reaction_priority = {
        ActionType.CHI: 1,
        ActionType.PONG: 2,
        ActionType.KONG: 2,
        ActionType.WIN: 3,
    }
    log_path = os.path.join(project_root, "simulation.log")

    memory_check = (
        bounded_python_memory_growth()
        if check_memory == "1"
        else nullcontext()
    )
    with (
        memory_check as memory_report,
        open(log_path, "w", encoding="utf-8") as log_file,
        log_simulation_errors(log_file),
    ):
        for game_number in range(games_to_run):
            rng = Random(game_number)
            state = GameState(
                game_id=f"simulation-{game_number}",
                dealer=game_number % 4,
                players={seat: PlayerState(seat_id=seat) for seat in range(4)},
                wall=create_shuffled_wall(rng),
            )
            state.deal(config)
            assert_card_conservation(
                state,
                game_number=game_number,
                phase="after deal",
            )

            winners = []
            steps = 0
            if state.is_basic_win(state.current_turn):
                winners = [state.current_turn]
                state.complete_round(winner_id=state.current_turn)

            for turn_number in range(200):
                if state.is_over:
                    break

                steps += 1
                player_id = state.current_turn
                player = state.players[player_id]
                last_drawn_tile = None

                standing_hand_size = config.hand_size - 3 * len(player.melds)
                if len(player.hand) == standing_hand_size:
                    dealer_before_draw = state.dealer
                    lian_zhuang_before_draw = state.lian_zhuang
                    current_turn_before_draw = state.current_turn
                    draw_action = state.draw_tile(
                        config=config,
                        validate_card_conservation=True,
                    )
                    assert_card_conservation(
                        state,
                        game_number=game_number,
                        phase="after draw and flower replacement",
                    )
                    if draw_action is None:
                        assert state.is_over, (
                            "A failed draw must settle the round in GameState"
                        )
                        assert state.dealer == dealer_before_draw
                        assert state.lian_zhuang == lian_zhuang_before_draw + 1
                        assert state.current_turn == current_turn_before_draw
                        break
                    last_drawn_tile = draw_action.tile_id

                assert len(player.hand) == standing_hand_size + 1, (
                    f"Unexpected hand size before action in game {game_number}: "
                    f"player={player_id}, hand={len(player.hand)}, "
                    f"expected={standing_hand_size + 1}"
                )

                legal_actions = action_generator.get_turn_player_actions(
                    hand=player.hand,
                    last_drawn_tile=last_drawn_tile,
                    can_win_self_draw=state.is_basic_win(player_id),
                )
                playable_actions = [
                    action
                    for action in legal_actions
                    if action.action_type in (ActionType.DISCARD, ActionType.WIN)
                ]
                assert playable_actions, f"No playable actions in game {game_number}"

                legal_actions = actions_to_legal_actions(playable_actions)
                observation = game_state_to_observation(state, player_id)
                decision = policy.decide(observation, legal_actions)
                policy_decisions += 1
                chosen_action = next(
                    action
                    for action, legal_action in zip(playable_actions, legal_actions)
                    if legal_action == decision.action
                )
                if chosen_action.action_type == ActionType.WIN:
                    winners = [player_id]
                    state.complete_round(winner_id=player_id)
                else:
                    state.apply_action(
                        player_id,
                        chosen_action,
                        config=config,
                        validate_card_conservation=True,
                    )
                    assert_card_conservation(
                        state,
                        game_number=game_number,
                        phase="after discard",
                    )
                    last_discard = state.last_discard
                    assert last_discard is not None
                    reactions = {}
                    for reacting_player_id, reacting_player in state.players.items():
                        if reacting_player_id == player_id:
                            continue

                        can_win = is_basic_win(
                            reacting_player.hand + [last_discard.tile_id],
                            meld_count=len(reacting_player.melds),
                        )
                        available_actions = action_generator.get_response_actions(
                            hand=reacting_player.hand,
                            target_tile=last_discard.tile_id,
                            is_previous_player=(
                                reacting_player_id == (player_id + 1) % 4
                            ),
                            can_win_honin=can_win,
                            passed_win=reacting_player.passed_win,
                        )
                        reaction = preferred_reaction(available_actions)
                        if reaction is not None:
                            reactions[reacting_player_id] = reaction

                    reaction_checks += 1
                    reaction_opportunities += len(reactions)
                    contested_reactions += len(reactions) > 1
                    resolved = state.resolve_reaction_priority(reactions, config=config)
                    if resolved:
                        resolved_reactions += 1
                        reaction_actions += len(resolved)
                        highest_priority = max(
                            reaction_priority[candidate.action_type]
                            for candidate in reactions.values()
                        )
                        highest_priority_reactions = {
                            candidate_player_id: candidate
                            for candidate_player_id, candidate in reactions.items()
                            if reaction_priority[candidate.action_type]
                            == highest_priority
                        }
                        expected_player_id = min(
                            highest_priority_reactions,
                            key=lambda candidate_player_id: (
                                candidate_player_id - player_id
                            )
                            % 4,
                        )
                        expected_reactions = {
                            expected_player_id: highest_priority_reactions[
                                expected_player_id
                            ]
                        }
                        assert resolved == expected_reactions, (
                            f"Reaction priority mismatch in game {game_number}: {reactions}"
                        )
                        assert len(resolved) == 1, (
                            f"Only one reaction may be resolved: {resolved}"
                        )
                        reacting_player_id, reaction = next(iter(resolved.items()))
                        if reaction.action_type == ActionType.WIN:
                            winners = list(resolved)
                            state.complete_round(winner_id=reacting_player_id)
                        else:
                            state.apply_action(
                                reacting_player_id,
                                reaction,
                                config=config,
                                validate_card_conservation=True,
                            )
                            assert_card_conservation(
                                state,
                                game_number=game_number,
                                phase=f"after {reaction.action_type} claim",
                            )

            else:
                raise AssertionError(f"Game {game_number} did not finish within 200 turns")

            assert state.is_over, f"Game {game_number} ended without a terminal state"
            assert_card_conservation(
                state,
                game_number=game_number,
                phase="round end",
            )
            completed_games += 1
            total_steps += steps
            if not winners:
                draws += 1
            else:
                wins += 1
                assert len(winners) == 1
            if (game_number + 1) % 100 == 0:
                log_file.write(
                    f"Completed {game_number + 1} games; latest game ended "
                    f"after {steps} turns\n"
                )
                log_file.flush()

    win_rate = wins / completed_games if completed_games else 0.0
    average_steps = total_steps / completed_games if completed_games else 0.0
    memory_summary = ""
    if memory_report is not None:
        memory_growth = memory_report["growth_bytes"]
        memory_limit = memory_report["max_growth_bytes"]
        memory_summary = (
            f", memory_growth={memory_growth} bytes "
            f"({memory_growth / (1024 * 1024):.2f} MiB), "
            f"memory_limit={memory_limit} bytes "
            f"({memory_limit / (1024 * 1024):.2f} MiB)"
        )
    print(
        f"Simulation summary: games={completed_games}, wins={wins}, "
        f"win_rate={win_rate:.1%}, draws={draws}, total_steps={total_steps}, "
        f"average_steps={average_steps:.2f}, decisions={policy_decisions}, "
        f"reaction_actions={reaction_actions}, "
        f"reaction_checks={reaction_checks}, "
        f"reaction_opportunities={reaction_opportunities}, "
        f"contested_reactions={contested_reactions}, "
        f"resolved_reactions={resolved_reactions}, "
        f"log={log_path}{memory_summary}"
    )
    if memory_report is not None and memory_report["growth_bytes"] > memory_report["max_growth_bytes"]:
        raise AssertionError(
            f"Python memory grew by {memory_report['growth_bytes']} bytes "
            f"(limit: {memory_report['max_growth_bytes']} bytes)"
        )
    assert completed_games == games_to_run
    assert policy_decisions > 0
    assert reaction_checks > 0
    if games_to_run >= 100:
        assert reaction_opportunities > 0
        assert contested_reactions > 0
        assert resolved_reactions > 0
