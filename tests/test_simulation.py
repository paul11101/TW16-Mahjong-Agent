import traceback
from contextlib import contextmanager
import os
import sys
from random import Random

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from src.common.schemas import ActionType
from src.rules.game_state import GameState, PlayerState, create_shuffled_wall
from src.rules.legal_actions import LegalActionGenerator
from src.rules.rule import RulesetConfig
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


def test_100_random_games_complete_without_unexpected_exceptions():
    config = RulesetConfig()
    action_generator = LegalActionGenerator(config)
    policy = BaselinePolicy(calculator=Taiwan16ShantenCalculator())
    completed_games = 0
    wins = 0
    draws = 0
    total_steps = 0
    policy_decisions = 0
    log_path = os.path.join(project_root, "simulation.log")

    with open(log_path, "w", encoding="utf-8") as log_file, log_simulation_errors(log_file):
        for game_number in range(100):
            rng = Random(game_number)
            state = GameState(
                game_id=f"simulation-{game_number}",
                dealer=game_number % 4,
                players={seat: PlayerState(seat_id=seat) for seat in range(4)},
                wall=create_shuffled_wall(rng),
            )
            state.deal(config)

            winner = None
            steps = 0
            if state.is_basic_win(state.current_turn):
                winner = state.current_turn
                state.is_over = True

            for turn_number in range(200):
                if state.is_over:
                    break

                steps += 1
                player_id = state.current_turn
                player = state.players[player_id]
                last_drawn_tile = None

                if len(player.hand) == config.hand_size:
                    draw_action = state.draw_tile(config=config)
                    if draw_action is None:
                        state.is_over = True
                        break
                    last_drawn_tile = draw_action.tile_id

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
                    winner = player_id
                    state.is_over = True
                else:
                    state.apply_action(player_id, chosen_action)

            else:
                raise AssertionError(f"Game {game_number} did not finish within 200 turns")

            assert state.is_over, f"Game {game_number} ended without a terminal state"
            completed_games += 1
            total_steps += steps
            if winner is None:
                draws += 1
            else:
                wins += 1
                log_file.write(
                    f"Game {game_number + 1}: player {winner} won after {steps} turns\n"
                )
                log_file.flush()

    win_rate = wins / completed_games if completed_games else 0.0
    average_steps = total_steps / completed_games if completed_games else 0.0
    print(
        f"Simulation summary: games={completed_games}, wins={wins}, "
        f"win_rate={win_rate:.1%}, draws={draws}, "
        f"average_steps={average_steps:.2f}, decisions={policy_decisions}, "
        f"log={log_path}"
    )
    assert completed_games == 100
    assert policy_decisions > 0
