import traceback
from contextlib import contextmanager, nullcontext
import gc
from io import StringIO
import os
import sys
from random import Random
from time import perf_counter
from typing import Any, Callable, TextIO
import pytest

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from src.common.schemas import ActionType
from src.rules.game_state import GameState, PlayerState, create_shuffled_wall, is_basic_win
from src.rules.legal_actions import LegalActionGenerator
from src.rules.rule import Action, RuleMechanics, RulesetConfig
from src.strategy.adapters import actions_to_legal_actions, game_state_to_observation
from src.strategy.baseline import BaselinePolicy
from src.strategy.interfaces import Decision
from src.strategy.shanten import Taiwan16ShantenCalculator

REACTION_PRIORITIES = {
    ActionType.CHI: 1,
    ActionType.PONG: 2,
    ActionType.KONG: 2,
    ActionType.WIN: 3,
}


class IllegalAction(AssertionError):
    """A simulator-selected action was not among the generated legal actions."""


def _simulation_state_snapshot(state: GameState) -> dict[str, Any]:
    return {
        "game_id": state.game_id,
        "current_turn": state.current_turn,
        "dealer": state.dealer,
        "wall_count": state.wall_count,
        "wall_including_reserved_tiles": list(state.wall),
        "last_discard": (
            None
            if state.last_discard is None
            else {
                "player_id": state.last_discard.player_id,
                "tile_id": state.last_discard.tile_id,
            }
        ),
        "players": {
            seat: {
                "hand": list(player.hand),
                "discards": list(player.discards),
                "flowers": list(player.flowers),
                "melds": [
                    {
                        "type": str(meld.meld_type),
                        "tiles": list(meld.tiles),
                        "from_player": meld.from_player,
                    }
                    for meld in player.melds
                ],
            }
            for seat, player in state.players.items()
        },
    }


def assert_simulation_action_is_legal(
    action: Any,
    legal_actions,
    *,
    state: GameState,
    game_number: int,
    seat: int,
    phase: str,
    illegal_number: int,
    log_file: TextIO,
    invalid_reason: str | None = None,
) -> None:
    if invalid_reason is None and action in legal_actions:
        return

    message = (
        f"IllegalAction #{illegal_number}: game={game_number}, seat={seat}, "
        f"phase={phase}, reason={invalid_reason or 'action not generated as legal'}, "
        f"action={action!r}, legal_actions={list(legal_actions)!r}, "
        f"board={_simulation_state_snapshot(state)!r}"
    )
    log_file.write(message + "\n")
    log_file.flush()
    raise IllegalAction(message)


def _current_process_memory_bytes() -> int:
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        class ProcessMemoryCounters(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
                ("PrivateUsage", ctypes.c_size_t),
            ]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        psapi.GetProcessMemoryInfo.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(ProcessMemoryCounters),
            wintypes.DWORD,
        ]
        psapi.GetProcessMemoryInfo.restype = wintypes.BOOL

        counters = ProcessMemoryCounters()
        counters.cb = ctypes.sizeof(counters)
        if not psapi.GetProcessMemoryInfo(
            kernel32.GetCurrentProcess(),
            ctypes.byref(counters),
            counters.cb,
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        return counters.PrivateUsage

    if sys.platform.startswith("linux"):
        with open("/proc/self/statm", encoding="ascii") as statm:
            resident_pages = int(statm.read().split()[1])
        return resident_pages * os.sysconf("SC_PAGE_SIZE")

    raise RuntimeError("Process memory tracking is supported on Windows and Linux")


@contextmanager
def log_simulation_errors(log_file):
    try:
        yield
    except Exception:
        log_file.write(f"ERROR\n{traceback.format_exc()}\n")
        log_file.flush()
        raise


@contextmanager
def bounded_python_memory_growth(
    max_growth_bytes=64 * 1024 * 1024,
    memory_reader: Callable[[], int] | None = None,
):
    memory_reader = memory_reader or _current_process_memory_bytes
    gc.collect()
    baseline = memory_reader()
    report = {
        "baseline_bytes": baseline,
        "memory_source": (
            "process_private_bytes" if os.name == "nt" else "resident_set_bytes"
        ),
    }
    try:
        yield report
    finally:
        gc.collect()
        current = memory_reader()
        report["current_bytes"] = current
        report["growth_bytes"] = current - baseline
        report["max_growth_bytes"] = max_growth_bytes


def test_bounded_python_memory_growth_reports_final_measurement():
    readings = iter((10_000, 12_048))

    with bounded_python_memory_growth(
        memory_reader=lambda: next(readings)
    ) as report:
        retained_allocation = bytearray(1024)

    assert report["growth_bytes"] == 2_048
    assert report["current_bytes"] - report["baseline_bytes"] == report["growth_bytes"]
    assert report["max_growth_bytes"] == 64 * 1024 * 1024
    del retained_allocation


def test_illegal_simulation_action_logs_the_current_board():
    state = GameState(
        game_id="illegal-action-report-test",
        players={seat: PlayerState(seat_id=seat) for seat in range(4)},
    )
    report = StringIO()

    with pytest.raises(IllegalAction, match="IllegalAction #1"):
        assert_simulation_action_is_legal(
            Action(action_type=ActionType.DISCARD, tile_id=0),
            [],
            state=state,
            game_number=7,
            seat=2,
            phase="discard decision",
            illegal_number=1,
            log_file=report,
        )

    logged = report.getvalue()
    assert "illegal-action-report-test" in logged
    assert "wall_including_reserved_tiles" in logged
    assert "players" in logged


def assert_card_conservation(state, *, game_number, phase):
    state.assert_card_conservation(
        phase=f"simulation game {game_number}: {phase}"
    )


def preferred_reaction(actions):
    """Select each player's strongest available response before arbitration."""
    best_action = None
    best_priority = 0
    for action in actions:
        priority = REACTION_PRIORITIES.get(action.action_type, 0)
        if priority > best_priority:
            best_action = action
            best_priority = priority
    return best_action


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
    illegal_action_count = 0
    log_path = os.path.join(project_root, "simulation.log")

    memory_check = (
        bounded_python_memory_growth()
        if check_memory == "1"
        else nullcontext()
    )
    started_at = perf_counter()
    with (
        memory_check as memory_report,
        open(log_path, "w", encoding="utf-8") as log_file,
        log_simulation_errors(log_file),
    ):
        def verify_action(action, legal_actions, *, game_number, seat, phase, reason=None):
            nonlocal illegal_action_count
            try:
                assert_simulation_action_is_legal(
                    action,
                    legal_actions,
                    state=state,
                    game_number=game_number,
                    seat=seat,
                    phase=phase,
                    illegal_number=illegal_action_count + 1,
                    log_file=log_file,
                    invalid_reason=reason,
                )
            except IllegalAction:
                illegal_action_count += 1
                raise

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

                policy_legal_actions = actions_to_legal_actions(playable_actions)
                observation = game_state_to_observation(state, player_id)
                decision = policy.decide(observation, policy_legal_actions)
                policy_decisions += 1
                if not isinstance(decision, Decision):
                    verify_action(
                        decision,
                        policy_legal_actions,
                        game_number=game_number,
                        seat=player_id,
                        phase="turn policy decision",
                        reason="policy did not return a Decision",
                    )
                verify_action(
                    decision.action,
                    policy_legal_actions,
                    game_number=game_number,
                    seat=player_id,
                    phase="turn policy decision",
                )
                chosen_action = playable_actions[
                    policy_legal_actions.index(decision.action)
                ]
                if chosen_action.action_type == ActionType.WIN:
                    winners = [player_id]
                    state.complete_round(winner_id=player_id)
                else:
                    state.apply_action(
                        player_id,
                        chosen_action,
                        config=config,
                        validate_card_conservation=True,
                        legal_action_generator=action_generator,
                    )
                    last_discard = state.last_discard
                    assert last_discard is not None
                    reactions = {}
                    response_actions_by_player = {}
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
                        response_actions_by_player[reacting_player_id] = available_actions
                        reaction = preferred_reaction(available_actions)
                        if reaction is not None:
                            verify_action(
                                reaction,
                                available_actions,
                                game_number=game_number,
                                seat=reacting_player_id,
                                phase="reaction decision",
                            )
                            reactions[reacting_player_id] = reaction

                    reaction_checks += 1
                    reaction_opportunities += len(reactions)
                    contested_reactions += len(reactions) > 1
                    resolved = state.resolve_reaction_priority(reactions, config=config)
                    if resolved:
                        resolved_reactions += 1
                        reaction_actions += len(resolved)
                        for reacting_player_id, reaction in resolved.items():
                            verify_action(
                                reaction,
                                response_actions_by_player.get(reacting_player_id, ()),
                                game_number=game_number,
                                seat=reacting_player_id,
                                phase="reaction priority resolution",
                            )
                            if reactions.get(reacting_player_id) != reaction:
                                verify_action(
                                    reaction,
                                    (),
                                    game_number=game_number,
                                    seat=reacting_player_id,
                                    phase="reaction priority resolution",
                                    reason="resolved action was not submitted by the player",
                                )
                        highest_priority = max(
                            REACTION_PRIORITIES[candidate.action_type]
                            for candidate in reactions.values()
                        )
                        highest_priority_reactions = {
                            candidate_player_id: candidate
                            for candidate_player_id, candidate in reactions.items()
                            if REACTION_PRIORITIES[candidate.action_type]
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
                                legal_action_generator=action_generator,
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

    elapsed_seconds = perf_counter() - started_at
    win_rate = wins / completed_games if completed_games else 0.0
    average_steps = total_steps / completed_games if completed_games else 0.0
    memory_summary = ""
    if memory_report is not None:
        memory_growth = memory_report["growth_bytes"]
        memory_limit = memory_report["max_growth_bytes"]
        memory_summary = (
            f", memory_source={memory_report['memory_source']}, "
            f"memory_growth={memory_growth} bytes "
            f"({memory_growth / (1024 * 1024):.2f} MiB), "
            f"memory_limit={memory_limit} bytes "
            f"({memory_limit / (1024 * 1024):.2f} MiB)"
        )
    print(
        f"Simulation summary: games={completed_games}, wins={wins}, "
        f"win_rate={win_rate:.1%}, draws={draws}, total_steps={total_steps}, "
        f"average_steps={average_steps:.2f}, elapsed_seconds={elapsed_seconds:.2f}, "
        f"decisions={policy_decisions}, "
        f"reaction_actions={reaction_actions}, "
        f"illegal_actions={illegal_action_count}, "
        f"reaction_checks={reaction_checks}, "
        f"reaction_opportunities={reaction_opportunities}, "
        f"contested_reactions={contested_reactions}, "
        f"resolved_reactions={resolved_reactions}, "
        f"log={log_path}{memory_summary}"
    )
    if memory_report is not None and memory_report["growth_bytes"] > memory_report["max_growth_bytes"]:
        raise AssertionError(
            f"Process memory grew by {memory_report['growth_bytes']} bytes "
            f"(limit: {memory_report['max_growth_bytes']} bytes)"
        )
    assert completed_games == games_to_run
    assert policy_decisions > 0
    assert reaction_checks > 0
    assert illegal_action_count == 0
    if games_to_run >= 100:
        assert reaction_opportunities > 0
        assert contested_reactions > 0
        assert resolved_reactions > 0
