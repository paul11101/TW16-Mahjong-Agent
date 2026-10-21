import traceback
from contextlib import contextmanager
import os
import sys
from random import Random

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


def test_100_random_games_complete_without_unexpected_exceptions():
    config = RulesetConfig(
        rule_mechanics=RuleMechanics(
            strict_pass_rule=True,
            multi_winner=True,
            reserved_wall_tiles=16,
        ),
    )
    action_generator = LegalActionGenerator(config)
    policy = BaselinePolicy(calculator=Taiwan16ShantenCalculator())
    completed_games = 0
    wins = 0
    multi_ron_rounds = 0
    draws = 0
    total_steps = 0
    policy_decisions = 0
    reaction_checks = 0
    reaction_opportunities = 0
    contested_reactions = 0
    resolved_reactions = 0
    reaction_priority = {
        ActionType.CHI: 1,
        ActionType.PONG: 2,
        ActionType.KONG: 2,
        ActionType.WIN: 3,
    }
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
            initial_flowers = [
                f"Player {seat}={state.players[seat].flowers}"
                for seat in range(4)
                if state.players[seat].flowers
            ]
            if initial_flowers:
                log_file.write(
                    f"Game {game_number + 1}: Flowers dealt: "
                    f"{'; '.join(initial_flowers)}\n"
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
                    flower_count = len(player.flowers)
                    draw_action = state.draw_tile(config=config)
                    for flower_tile in player.flowers[flower_count:]:
                        log_file.write(
                            f"Game {game_number + 1}, turn {steps}: "
                            f"Player {player_id} replaced flower {flower_tile}\n"
                        )
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
                    winners = [player_id]
                    state.complete_round(winner_id=player_id)
                else:
                    log_file.write(
                        f"Game {game_number + 1}, turn {steps}: "
                        f"Player {player_id} discarded tile {chosen_action.tile_id}\n"
                    )
                    state.apply_action(player_id, chosen_action, config=config)
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
                        if (
                            highest_priority == reaction_priority[ActionType.WIN]
                            and config.rule_mechanics.multi_winner
                        ):
                            expected_reactions = highest_priority_reactions
                        else:
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
                        reacting_player_id, reaction = next(iter(resolved.items()))
                        if reaction.action_type == ActionType.WIN:
                            winners = list(resolved)
                            dealer_winner = (
                                state.dealer
                                if state.dealer in winners
                                else winners[0]
                            )
                            state.complete_round(winner_id=dealer_winner)
                        else:
                            if reaction.action_type == ActionType.CHI:
                                reaction_detail = (
                                    f"CHI {reaction.sequence} using tile "
                                    f"{last_discard.tile_id}"
                                )
                            elif reaction.action_type == ActionType.KONG:
                                reaction_detail = (
                                    f"KONG ({reaction.kong_type}) using tile "
                                    f"{last_discard.tile_id}"
                                )
                            else:
                                reaction_detail = (
                                    f"PONG using tile {last_discard.tile_id}"
                                )
                            log_file.write(
                                f"Game {game_number + 1}, turn {steps}: "
                                f"Player {reacting_player_id} {reaction_detail} "
                                f"from Player {player_id}'s discard\n"
                            )
                            replacement = state.apply_action(
                                reacting_player_id,
                                reaction,
                                config=config,
                            )
                            if (
                                reaction.action_type == ActionType.KONG
                                and replacement is None
                            ):
                                state.is_over = True

            else:
                raise AssertionError(f"Game {game_number} did not finish within 200 turns")

            assert state.is_over, f"Game {game_number} ended without a terminal state"
            completed_games += 1
            total_steps += steps
            if not winners:
                draws += 1
            else:
                wins += 1
                if len(winners) > 1:
                    multi_ron_rounds += 1
                log_file.write(
                    f"Game {game_number + 1}: player(s) {winners} won "
                    f"after {steps} turns\n"
                )
                log_file.flush()

    win_rate = wins / completed_games if completed_games else 0.0
    average_steps = total_steps / completed_games if completed_games else 0.0
    print(
        f"Simulation summary: games={completed_games}, wins={wins}, "
        f"multi_ron_rounds={multi_ron_rounds}, "
        f"win_rate={win_rate:.1%}, draws={draws}, "
        f"average_steps={average_steps:.2f}, decisions={policy_decisions}, "
        f"reaction_checks={reaction_checks}, "
        f"reaction_opportunities={reaction_opportunities}, "
        f"contested_reactions={contested_reactions}, "
        f"resolved_reactions={resolved_reactions}, "
        f"log={log_path}"
    )
    assert completed_games == 100
    assert policy_decisions > 0
    assert reaction_checks > 0
    assert reaction_opportunities > 0
    assert contested_reactions > 0
    assert resolved_reactions > 0
