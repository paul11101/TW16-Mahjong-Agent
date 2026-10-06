import os
import sys
from random import Random

import pytest

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from src.common.schemas import ActionType
from src.rules.game_state import GameState, PlayerState, create_shuffled_wall
from src.rules.legal_actions import LegalActionGenerator
from src.rules.rule import RulesetConfig


def test_100_random_games_complete_without_unexpected_exceptions():
    config = RulesetConfig()
    action_generator = LegalActionGenerator(config)
    completed_games = 0
    wins = 0
    draws = 0
    total_steps = 0
    log_path = os.path.join(project_root, "simulation.log")

    with open(log_path, "w", encoding="utf-8") as log_file:
        for game_number in range(100):
            rng = Random(game_number)
            state = GameState(
                game_id=f"simulation-{game_number}",
                dealer=game_number % 4,
                players={seat: PlayerState(seat_id=seat) for seat in range(4)},
                wall=create_shuffled_wall(rng),
            )
            state.deal(config)
            log_file.write(
                f"Game {game_number + 1}\n"
                f"  Dealer: {state.dealer}\n"
                f"  Wall: {state.wall_count}\n"
                "  Hands:\n"
            )
            for seat in range(4):
                log_file.write(f"    Player {seat}: {state.players[seat].hand}\n")
            log_file.write("  Flowers:\n")
            for seat in range(4):
                log_file.write(f"    Player {seat}: {state.players[seat].flowers}\n")
            log_file.write("\n")

            winner = None
            steps = 0
            if state.is_basic_win(state.current_turn):
                winner = state.current_turn
                state.is_over = True
                log_file.write(f"  Initial hand win: player {winner}\n")

            for turn_number in range(200):
                if state.is_over:
                    break

                steps += 1
                player_id = state.current_turn
                player = state.players[player_id]
                last_drawn_tile = None
                replacements = []

                if len(player.hand) == config.hand_size:
                    flowers_before_draw = len(player.flowers)
                    draw_action = state.draw_tile(config=config)
                    if draw_action is None:
                        state.is_over = True
                        log_file.write(
                            f"  Turn {turn_number + 1}\n"
                            f"    Player: {player_id}\n"
                            "    Draw: wall exhausted\n"
                            "    Flower replacement: none\n"
                            "    Legal action count: 0\n"
                            "    Chosen: none (round draw)\n"
                        )
                        break
                    last_drawn_tile = draw_action.tile_id
                    replacements = player.flowers[flowers_before_draw:]

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

                chosen_action = rng.choice(playable_actions)
                if chosen_action.action_type == ActionType.WIN:
                    chosen_description = f"WIN with tile {chosen_action.tile_id}"
                else:
                    chosen_description = f"DISCARD tile {chosen_action.tile_id}"
                log_file.write(
                    f"  Turn {turn_number + 1}\n"
                    f"    Player: {player_id}\n"
                    f"    Draw: {last_drawn_tile if last_drawn_tile is not None else 'none (initial hand)'}\n"
                    f"    Flower replacement: {replacements or 'none'}\n"
                    f"    Legal action count: {len(playable_actions)}\n"
                    f"    Chosen: {chosen_description}\n"
                )
                if chosen_action.action_type == ActionType.WIN:
                    winner = player_id
                    state.is_over = True
                    log_file.write(f"  Game won by player {winner}\n")
                else:
                    state.apply_action(player_id, chosen_action)

            else:
                pytest.fail(f"Game {game_number} did not finish within 200 turns")

            assert state.is_over, f"Game {game_number} ended without a terminal state"
            completed_games += 1
            total_steps += steps
            if winner is None:
                draws += 1
                log_file.write(f"  Result: draw after {steps} turns\n\n")
            else:
                wins += 1
                log_file.write(
                    f"  Result: player {winner} won after {steps} turns\n\n"
                )

    win_rate = wins / completed_games if completed_games else 0.0
    average_steps = total_steps / completed_games if completed_games else 0.0
    print(
        f"Simulation summary: games={completed_games}, wins={wins}, "
        f"win_rate={win_rate:.1%}, draws={draws}, "
        f"average_steps={average_steps:.2f}, log={log_path}"
    )
    assert completed_games == 100
