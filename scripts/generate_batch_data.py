"""Generate streamed VLOG-BC-style JSONL data from the frozen Taiwanese rules engine."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Iterable, Iterator

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.common.schemas import ActionType
from src.rules.opponent_pool import SEAT_NAMES, OpponentPool
from src.rules.game_result import GameResult
from src.rules.rule import RulesetConfig
from src.strategy.evaluation_game import play_round
from src.strategy.evaluation_plan import EvaluationGame, make_game_state
from src.strategy.interfaces import Decision, LegalActions, Observation
from src.strategy.data_generation_version import DATA_GEN_VERSION
from src.strategy.ruleset_validation import validate_ruleset_version
from src.rules.weighted_policy import WeightedPolicyWrapper


def load_config(path: Path | None) -> dict:
    if path is None:
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("config must contain a JSON object")
    return data


def validate_positive_int(name: str, value: object) -> int:
    if type(value) is not int or value < 1:
        raise ValueError(f"{name} must be a positive integer")
    return value


def validate_nonnegative_int(name: str, value: object) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value


class BatchRecordingPolicy:
    """Record a seat's weighted Bot decisions and its game's full Bot lineup."""

    def __init__(
        self,
        game_id: str,
        seed: int,
        ruleset_version: str,
        bot_style: str,
        bot_styles: tuple[str, str, str, str],
        policy: WeightedPolicyWrapper,
        records: list[dict],
    ) -> None:
        validate_ruleset_version(ruleset_version)
        self.policy = policy
        self.game_id = game_id
        self.seed = seed
        self.ruleset_version = ruleset_version
        self.bot_style = bot_style
        self.bot_styles = bot_styles
        self.records = records

    def decide(self, observation: Observation, legal_actions: LegalActions) -> Decision:
        actions = tuple(legal_actions)
        decision = self.policy.decide(observation, actions)
        if decision.action not in actions:
            raise ValueError(f"player {observation.seat} returned an illegal action")

        self.records.append({
            "data_gen_version": DATA_GEN_VERSION,
            "game_id": self.game_id,
            "decision_id": str(len(self.records)),
            "base_seed": self.seed,
            "bot_style": self.bot_style,
            "game_metadata": {
                "seat_names": list(SEAT_NAMES),
                "bot_styles": list(self.bot_styles),
            },
            "observation": _observation_dict(observation),
            "legal_actions": [_legal_action_dict(action) for action in actions],
            "action": _legal_action_dict(decision.action),
            "ruleset_version": self.ruleset_version,
            "strategy_version": self.policy.strategy_version,
        })
        return decision


def _attach_game_result(records: list[dict], result: GameResult) -> None:
    if not records:
        raise RuntimeError("completed game produced no decision records")
    records[-1]["game_metadata"]["terminal"] = {
        "completed": True,
        "decision_count": len(records),
        "result": result.to_dict(),
    }


def _action_type_value(value: object) -> str:
    if isinstance(value, ActionType):
        return value.value
    if hasattr(value, "value"):
        return str(value.value)
    return str(value)


def _observation_dict(observation: Observation) -> dict:
    return {
        "hand": list(observation.hand),
        "melds": [
            [list(meld) for meld in player_melds]
            for player_melds in observation.melds
        ],
        "flowers": [list(player_flowers) for player_flowers in observation.flowers],
        "discards": [list(player_discards) for player_discards in observation.discards],
        "remaining_tiles": observation.remaining_tiles,
        "current_player": observation.current_player,
        "seat": observation.seat,
        "round_wind": observation.round_wind,
        "seat_wind": observation.seat_wind,
    }


def _legal_action_dict(action) -> dict:
    return {
        "id": action.id,
        "action": _action_type_value(action.action),
        "tile": action.tile,
        "tiles": list(action.tiles),
        "kong_type": action.kong_type,
    }


def iter_game_records(
    num_games: int,
    base_seed: int,
    config: RulesetConfig | None = None,
    opponent_pool: OpponentPool | None = None,
) -> Iterator[dict]:
    num_games = validate_positive_int("num_games", num_games)
    base_seed = validate_nonnegative_int("base_seed", base_seed)
    config = config or RulesetConfig()
    validate_ruleset_version(config.ruleset_version)
    opponent_pool = opponent_pool or OpponentPool()

    for game_number in range(num_games):
        seed = base_seed + game_number
        state = make_game_state(EvaluationGame(seed, 0), config)
        bot_styles, policies = opponent_pool.create_policies(seed)
        records: list[dict] = []
        seat_policies = tuple(
            BatchRecordingPolicy(
                state.game_id,
                seed,
                config.ruleset_version,
                bot_styles[seat],
                bot_styles,
                policies[seat],
                records,
            )
            for seat in range(4)
        )
        result = play_round(state, seat_policies, config)
        _attach_game_result(records, result)
        yield from records


def generate_batch_data(
    num_games: int,
    batch_size: int,
    base_seed: int,
    output_dir: str | Path,
    opponent_pool: OpponentPool | None = None,
) -> list[Path]:
    num_games = validate_positive_int("num_games", num_games)
    batch_size = validate_positive_int("batch_size", batch_size)
    base_seed = validate_nonnegative_int("base_seed", base_seed)

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    config = RulesetConfig()
    validate_ruleset_version(config.ruleset_version)
    opponent_pool = opponent_pool or OpponentPool()

    files: list[Path] = []
    batch_number = 0
    games_in_batch = 0
    stream = None

    try:
        for game_number in range(num_games):
            if games_in_batch == 0:
                batch_number += 1
                path = output_dir / f"vlog_bc_batch_{batch_number:06d}.jsonl"
                stream = path.open("x", encoding="utf-8", newline="\n")
                files.append(path)

            seed = base_seed + game_number
            state = make_game_state(EvaluationGame(seed, 0), config)
            bot_styles, policies = opponent_pool.create_policies(seed)
            records: list[dict] = []
            seat_policies = tuple(
                BatchRecordingPolicy(
                    state.game_id,
                    seed,
                    config.ruleset_version,
                    bot_styles[seat],
                    bot_styles,
                    policies[seat],
                    records,
                )
                for seat in range(4)
            )
            result = play_round(state, seat_policies, config)
            _attach_game_result(records, result)

            for record in records:
                stream.write(json.dumps(
                    record,
                    ensure_ascii=False,
                    allow_nan=False,
                    separators=(",", ":"),
                ) + "\n")

            games_in_batch += 1
            if games_in_batch == batch_size:
                stream.close()
                stream = None
                games_in_batch = 0
    finally:
        if stream is not None:
            stream.close()

    return files


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="批次產出台麻 VLOG-BC 訓練資料")
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s DATA_GEN_VERSION {DATA_GEN_VERSION}",
    )
    parser.add_argument("--config", type=Path, help="JSON 設定檔")
    parser.add_argument(
        "--opponent-pool-config",
        type=Path,
        help="JSON 對手權重設定檔（style: weight）",
    )
    parser.add_argument("--num-games", "--num_games", dest="num_games", type=int)
    parser.add_argument("--batch-size", "--batch_size", dest="batch_size", type=int)
    parser.add_argument("--base-seed", "--base_seed", dest="base_seed", type=int)
    parser.add_argument("--output-dir", "--output_dir", dest="output_dir", type=Path)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    config = load_config(args.config)
    num_games = args.num_games if args.num_games is not None else config.get("num_games", 100)
    batch_size = args.batch_size if args.batch_size is not None else config.get("batch_size", 10)
    base_seed = args.base_seed if args.base_seed is not None else config.get("base_seed", 0)
    output_dir = args.output_dir if args.output_dir is not None else config.get("output_dir", "data/batch_vlog_bc")
    opponent_weights = config.get("opponent_pool")

    try:
        num_games = validate_positive_int("num_games", num_games)
        batch_size = validate_positive_int("batch_size", batch_size)
        base_seed = validate_nonnegative_int("base_seed", base_seed)
        if args.opponent_pool_config is not None:
            opponent_weights = load_config(args.opponent_pool_config)
        if opponent_weights is not None and not isinstance(opponent_weights, dict):
            raise ValueError("opponent_pool must be a JSON object of style weights")
        pool = OpponentPool(opponent_weights)
        files = generate_batch_data(
            num_games,
            batch_size,
            base_seed,
            Path(output_dir),
            opponent_pool=pool,
        )
    except (OSError, ValueError, json.JSONDecodeError) as error:
        parser.exit(1, f"{error}\n")

    print(f"已產生 {num_games} 局：{Path(output_dir).resolve()}")
    print(f"輸出分片：{len(files)} 個 .jsonl 檔案")
    print(f"資料生成版本：{DATA_GEN_VERSION}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
