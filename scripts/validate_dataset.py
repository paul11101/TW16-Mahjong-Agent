"""Validate exported decision JSONL before using it as VLOG-BC data."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.common.schemas import ActionType
from src.opponent_pool import SEAT_NAMES
from src.rules.rule import RULESET_VERSION
from src.strategy.encoder import encode_observation
from src.strategy.feature_spec import FEATURE_SIZE
from src.strategy.interfaces import Observation
from src.strategy.data_generation_version import DATA_GEN_VERSION
from src.strategy.ruleset_validation import validate_ruleset_version
from src.weighted_policy import BOT_STYLE_PRESETS

RECORD_FIELDS = {
    "data_gen_version",
    "game_id",
    "decision_id",
    "base_seed",
    "bot_style",
    "game_metadata",
    "observation",
    "legal_actions",
    "action",
    "ruleset_version",
    "strategy_version",
}
OBSERVATION_FIELDS = {field.name for field in fields(Observation)}
ACTION_FIELDS = {"id", "action", "tile", "tiles", "kong_type"}
GAME_METADATA_FIELDS = {"seat_names", "bot_styles", "terminal"}
TERMINAL_FIELDS = {"completed", "decision_count", "result"}
RESULT_FIELDS = {
    "round_number",
    "round_label",
    "round_wind",
    "dealer_seat",
    "lianzhuang_count",
    "winner_seats",
    "loser_seat",
    "win_type",
    "total_fans",
    "fan_details",
    "winner_fan_results",
    "score_delta",
    "scores_dict",
}

SUGGESTIONS = {
    "action": "在 exporter 中以同一個 legal_actions 物件序列化選擇結果，並只輸出合法候選。",
    "observation": "只輸出 Observation schema 欄位；勿加入牌牆、他家手牌或其他私有狀態。",
    "sequence": "保留每局所有決策並依序輸出 decision_id；最後一筆附上完整結算摘要。",
    "result": "在 play_round 完成後序列化 GameResult.to_dict()，確認四家分數與勝負資料完整。",
    "format": "請依指定 JSON 型別／欄位輸出，並以 UTF-8 編碼寫入 JSONL。",
    "ruleset": "請使用目前 RulesetConfig 的凍結版本重新產生資料，不可混用不同規則版本。",
    "data_generation": "請確認資料由相同 DATA_GEN_VERSION 的 exporter 產生，再重新驗證完整資料集。",
}


@dataclass(frozen=True)
class ValidationIssue:
    line: int | None
    game_id: str | None
    category: str
    message: str
    recommendation: str


@dataclass(frozen=True)
class ValidationReport:
    records: int
    games: int
    error_count: int
    issues: tuple[ValidationIssue, ...]

    @property
    def valid(self) -> bool:
        return self.error_count == 0


class RecordError(ValueError):
    def __init__(self, category: str, message: str) -> None:
        super().__init__(message)
        self.category = category


def _require(condition: bool, category: str, message: str) -> None:
    if not condition:
        raise RecordError(category, message)


def _integer(value: object, *, minimum: int, maximum: int | None = None) -> bool:
    return (
        type(value) is int
        and value >= minimum
        and (maximum is None or value <= maximum)
    )


def _tile_list(value: object, *, minimum: int, maximum: int, label: str) -> list[int]:
    _require(isinstance(value, list), "observation", f"{label} must be a list")
    _require(
        all(_integer(tile, minimum=minimum, maximum=maximum) for tile in value),
        "observation",
        f"{label} contains an invalid tile id",
    )
    return value


def _validate_observation(data: object) -> tuple[Observation, int]:
    _require(isinstance(data, dict), "observation", "observation must be an object")
    missing = OBSERVATION_FIELDS - data.keys()
    extra = data.keys() - OBSERVATION_FIELDS
    _require(not missing, "observation", f"missing fields: {sorted(missing)}")
    _require(not extra, "observation", f"unexpected fields: {sorted(extra)}")

    hand = _tile_list(data["hand"], minimum=0, maximum=33, label="hand")
    _require(len(hand) <= 17, "observation", "hand has more than 17 tiles")

    discards_data = data["discards"]
    melds_data = data["melds"]
    flowers_data = data["flowers"]
    for label, groups in (
        ("discards", discards_data),
        ("melds", melds_data),
        ("flowers", flowers_data),
    ):
        _require(
            isinstance(groups, list) and len(groups) == 4,
            "observation",
            f"{label} must contain exactly four seat lists",
        )

    discards = tuple(
        tuple(_tile_list(group, minimum=0, maximum=33, label=f"discards[{seat}]"))
        for seat, group in enumerate(discards_data)
    )
    melds_by_seat = []
    for seat, seat_melds in enumerate(melds_data):
        _require(
            isinstance(seat_melds, list),
            "observation",
            f"melds[{seat}] must be a list",
        )
        melds = []
        for meld_index, meld in enumerate(seat_melds):
            tiles = _tile_list(
                meld,
                minimum=0,
                maximum=33,
                label=f"melds[{seat}][{meld_index}]",
            )
            _require(
                len(tiles) in (3, 4),
                "observation",
                "each meld must contain three or four tiles",
            )
            melds.append(tuple(tiles))
        melds_by_seat.append(tuple(melds))

    flowers = tuple(
        tuple(_tile_list(group, minimum=34, maximum=41, label=f"flowers[{seat}]"))
        for seat, group in enumerate(flowers_data)
    )
    for field in ("current_player", "seat", "round_wind", "seat_wind"):
        _require(
            _integer(data[field], minimum=0, maximum=3),
            "observation",
            f"{field} must be an integer from 0 to 3",
        )
    _require(
        _integer(data["remaining_tiles"], minimum=0, maximum=144),
        "observation",
        "remaining_tiles must be an integer from 0 to 144",
    )

    observation = Observation(
        hand=tuple(hand),
        discards=discards,
        melds=tuple(melds_by_seat),
        flowers=flowers,
        current_player=data["current_player"],
        seat=data["seat"],
        remaining_tiles=data["remaining_tiles"],
        round_wind=data["round_wind"],
        seat_wind=data["seat_wind"],
    )
    encoded = encode_observation(observation)
    _require(
        FEATURE_SIZE == 555 and len(encoded) == FEATURE_SIZE,
        "observation",
        f"encoded observation must have the frozen 555 features; got {len(encoded)}",
    )
    return observation, len(encoded)


def _validate_action(action: object, *, label: str) -> None:
    _require(isinstance(action, dict), "action", f"{label} must be an object")
    _require(
        action.keys() == ACTION_FIELDS,
        "action",
        f"{label} fields must be exactly {sorted(ACTION_FIELDS)}",
    )
    _require(
        isinstance(action["id"], str) and bool(action["id"].strip()),
        "action",
        f"{label}.id must be a non-empty string",
    )
    _require(
        action["action"] in {item.value for item in ActionType},
        "action",
        f"{label}.action is not a supported action type",
    )
    tile = action["tile"]
    _require(
        tile is None or _integer(tile, minimum=0, maximum=33),
        "action",
        f"{label}.tile must be null or a tile id from 0 to 33",
    )
    _tile_list(action["tiles"], minimum=0, maximum=33, label=f"{label}.tiles")
    _require(
        action["kong_type"] is None
        or action["kong_type"] in {"ming", "an", "jia"},
        "action",
        f"{label}.kong_type is invalid",
    )


def _validate_record(record: object) -> tuple[str, int, dict[str, Any], dict[str, Any]]:
    _require(isinstance(record, dict), "format", "each JSONL record must be an object")
    missing = RECORD_FIELDS - record.keys()
    extra = record.keys() - RECORD_FIELDS
    _require(not missing, "format", f"missing fields: {sorted(missing)}")
    _require(not extra, "format", f"unexpected fields: {sorted(extra)}")
    _require(
        record["data_gen_version"] == DATA_GEN_VERSION,
        "data_generation",
        (
            f"data_gen_version mismatch: expected {DATA_GEN_VERSION}, "
            f"found {record['data_gen_version']!r}"
        ),
    )
    _require(
        isinstance(record["game_id"], str) and bool(record["game_id"].strip()),
        "format",
        "game_id must be a non-empty string",
    )
    _require(
        isinstance(record["decision_id"], str)
        and record["decision_id"].isdigit(),
        "sequence",
        "decision_id must be a non-negative integer string",
    )
    _require(_integer(record["base_seed"], minimum=0), "format", "base_seed is invalid")
    try:
        validate_ruleset_version(record["ruleset_version"])
    except ValueError as error:
        raise RecordError("ruleset", str(error)) from error
    _require(
        isinstance(record["strategy_version"], str)
        and bool(record["strategy_version"].strip()),
        "format",
        "strategy_version must be a non-empty string",
    )

    observation, _ = _validate_observation(record["observation"])
    seat = observation.seat
    _require(
        isinstance(record["bot_style"], str)
        and record["bot_style"] in BOT_STYLE_PRESETS,
        "format",
        "bot_style is not a known weighted Bot style",
    )
    metadata = record["game_metadata"]
    _require(isinstance(metadata, dict), "sequence", "game_metadata must be an object")
    extra_metadata = metadata.keys() - GAME_METADATA_FIELDS
    _require(
        not extra_metadata,
        "format",
        f"unexpected game_metadata fields: {sorted(extra_metadata)}",
    )
    _require(
        metadata.get("seat_names") == list(SEAT_NAMES),
        "sequence",
        "game_metadata.seat_names must be east, south, west, north",
    )
    bot_styles = metadata.get("bot_styles")
    _require(
        isinstance(bot_styles, list)
        and len(bot_styles) == 4
        and all(style in BOT_STYLE_PRESETS for style in bot_styles),
        "sequence",
        "game_metadata.bot_styles must name four known styles",
    )
    _require(
        record["bot_style"] == bot_styles[seat],
        "sequence",
        "bot_style does not match the recorded seat lineup",
    )

    legal_actions = record["legal_actions"]
    _require(
        isinstance(legal_actions, list) and bool(legal_actions),
        "action",
        "legal_actions must be a non-empty list",
    )
    for index, legal_action in enumerate(legal_actions):
        _validate_action(legal_action, label=f"legal_actions[{index}]")
    action_ids = [item["id"] for item in legal_actions]
    _require(
        len(action_ids) == len(set(action_ids)),
        "action",
        "legal_actions contains duplicate action ids",
    )
    action = record["action"]
    _validate_action(action, label="action")
    _require(
        action in legal_actions,
        "action",
        "chosen action is not exactly present in legal_actions",
    )

    terminal = metadata.get("terminal")
    if terminal is not None:
        _require(isinstance(terminal, dict), "result", "terminal must be an object")
        _require(
            terminal.keys() == TERMINAL_FIELDS,
            "result",
            f"terminal fields must be exactly {sorted(TERMINAL_FIELDS)}",
        )
    return record["game_id"], seat, metadata, record


def _validate_result(result: object) -> None:
    _require(isinstance(result, dict), "result", "terminal result must be an object")
    _require(
        result.keys() == RESULT_FIELDS,
        "result",
        f"result fields must be exactly {sorted(RESULT_FIELDS)}",
    )
    _require(_integer(result["round_number"], minimum=1), "result", "round_number is invalid")
    wind = result["round_wind"]
    dealer = result["dealer_seat"]
    _require(_integer(wind, minimum=0, maximum=3), "result", "round_wind is invalid")
    _require(_integer(dealer, minimum=0, maximum=3), "result", "dealer_seat is invalid")
    _require(
        _integer(result["lianzhuang_count"], minimum=0),
        "result",
        "lianzhuang_count is invalid",
    )
    wind_names = ("東", "南", "西", "北")
    expected_label = f"{wind_names[wind]}風場第 {result['round_number']} 局"
    _require(result["round_label"] == expected_label, "result", "round_label is inconsistent")

    win_type = result["win_type"]
    _require(
        win_type in {"self_draw", "discard_win", "draw"},
        "result",
        "win_type is invalid",
    )
    winners = result["winner_seats"]
    _require(
        isinstance(winners, list)
        and all(_integer(seat, minimum=0, maximum=3) for seat in winners)
        and len(winners) == len(set(winners)),
        "result",
        "winner_seats must contain unique seats from 0 to 3",
    )
    loser = result["loser_seat"]
    if win_type == "draw":
        _require(not winners and loser is None, "result", "draw cannot include winners or a loser")
    elif win_type == "self_draw":
        _require(bool(winners) and loser is None, "result", "self-draw winner data is incomplete")
    else:
        _require(
            bool(winners)
            and _integer(loser, minimum=0, maximum=3)
            and loser not in winners,
            "result",
            "discard-win loser/winner data is invalid",
        )

    for field in ("score_delta", "scores_dict"):
        scores = result[field]
        _require(
            isinstance(scores, dict)
            and set(scores) == {"0", "1", "2", "3"}
            and all(_integer(value, minimum=-1_000_000) for value in scores.values()),
            "result",
            f"{field} must contain integer values for all four seats",
        )
    deltas = result["score_delta"]
    scores = result["scores_dict"]
    _require(sum(deltas.values()) == 0, "result", "score_delta must be zero-sum")
    starting_scores = {scores[seat] - deltas[seat] for seat in scores}
    _require(
        len(starting_scores) == 1 and next(iter(starting_scores)) == 20_000,
        "result",
        "scores_dict and score_delta do not reconcile to the 20,000-point starting scores",
    )

    fan_results = result["winner_fan_results"]
    _require(isinstance(fan_results, dict), "result", "winner_fan_results must be an object")
    _require(
        set(fan_results) == {str(seat) for seat in winners},
        "result",
        "winner_fan_results must contain every winner and no other seat",
    )
    if win_type == "draw":
        _require(
            result["total_fans"] is None
            and result["fan_details"] == []
            and fan_results == {},
            "result",
            "draw result cannot include fan data",
        )
    else:
        for seat_text, fan in fan_results.items():
            _require(
                isinstance(fan, dict)
                and fan.keys() == {"seat", "total_fans", "fan_details"},
                "result",
                "winner fan result has an invalid shape",
            )
            total = fan["total_fans"]
            details = fan["fan_details"]
            _require(
                _integer(total, minimum=0)
                and isinstance(details, list)
                and all(
                    isinstance(item, dict)
                    and item.keys() == {"name", "fans"}
                    and isinstance(item["name"], str)
                    and _integer(item["fans"], minimum=0)
                    for item in details
                )
                and sum(item["fans"] for item in details) == total,
                "result",
                f"fan details for seat {seat_text} do not sum to total_fans",
            )
        if len(winners) == 1:
            winner_fan = fan_results[str(winners[0])]
            _require(
                result["total_fans"] == winner_fan["total_fans"]
                and result["fan_details"] == winner_fan["fan_details"],
                "result",
                "single-winner fan summary is inconsistent",
            )
        else:
            _require(
                result["total_fans"] is None and result["fan_details"] == [],
                "result",
                "multi-winner result must keep fan data per winner",
            )


def validate_dataset(path: str | Path, *, max_errors: int = 100) -> ValidationReport:
    if type(max_errors) is not int or max_errors < 1:
        raise ValueError("max_errors must be a positive integer")

    issues: list[ValidationIssue] = []
    error_count = 0
    records_seen = 0
    games_seen = 0
    seen_game_ids: set[str] = set()

    current_game_id: str | None = None
    current_count = 0
    current_metadata: dict[str, Any] | None = None
    terminal: dict[str, Any] | None = None
    terminal_line: int | None = None
    current_last_line: int | None = None
    wind_observations: list[tuple[int, int, int, int]] = []
    current_winning_seats: list[int] = []

    def add_issue(
        line: int | None,
        game_id: str | None,
        category: str,
        message: str,
    ) -> None:
        nonlocal error_count
        error_count += 1
        if len(issues) < max_errors:
            issues.append(ValidationIssue(
                line=line,
                game_id=game_id,
                category=category,
                message=message,
                recommendation=SUGGESTIONS[category],
            ))

    def finish_game() -> None:
        if current_game_id is None:
            return
        if terminal is None or terminal_line != current_last_line:
            add_issue(
                current_last_line,
                current_game_id,
                "sequence",
                "game is missing its terminal summary on the final decision record",
            )
            return
        if terminal.get("completed") is not True:
            add_issue(terminal_line, current_game_id, "result", "terminal.completed must be true")
        if terminal.get("decision_count") != current_count:
            add_issue(
                terminal_line,
                current_game_id,
                "sequence",
                f"terminal decision_count is {terminal.get('decision_count')}, found {current_count}",
            )
        try:
            _validate_result(terminal.get("result"))
            assert current_metadata is not None
            result = terminal["result"]
            for seat, seat_wind, round_wind, line in wind_observations:
                _require(
                    seat_wind == (seat - result["dealer_seat"]) % 4,
                    "observation",
                    "seat_wind is inconsistent with dealer_seat",
                )
                _require(
                    round_wind == result["round_wind"],
                    "observation",
                    "round_wind is inconsistent with terminal result",
                )
            winning_actions = set(current_winning_seats)
            winners = set(result["winner_seats"])
            _require(
                winning_actions == winners,
                "result",
                "WIN decisions do not match the terminal winner_seats",
            )
        except (RecordError, KeyError, TypeError) as error:
            category = error.category if isinstance(error, RecordError) else "result"
            add_issue(terminal_line, current_game_id, category, str(error))

    try:
        stream = Path(path).open("rb")
    except OSError:
        raise

    with stream:
        for line_number, raw_line in enumerate(stream, start=1):
            try:
                record = json.loads(raw_line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                add_issue(
                    line_number,
                    current_game_id,
                    "format",
                    f"invalid UTF-8 JSONL record: {error}",
                )
                continue
            records_seen += 1
            game_id = record.get("game_id") if isinstance(record, dict) else None
            if not isinstance(game_id, str) or not game_id:
                add_issue(line_number, None, "format", "game_id is missing or invalid")
                continue

            if game_id != current_game_id:
                finish_game()
                if game_id in seen_game_ids:
                    add_issue(
                        line_number,
                        game_id,
                        "sequence",
                        "game records are split into multiple non-contiguous blocks",
                    )
                seen_game_ids.add(game_id)
                games_seen += 1
                current_game_id = game_id
                current_count = 0
                current_metadata = None
                terminal = None
                terminal_line = None
                current_last_line = None
                wind_observations = []
                current_winning_seats = []

            current_last_line = line_number
            try:
                parsed_game_id, seat, metadata, parsed_record = _validate_record(record)
                _require(
                    parsed_game_id == current_game_id,
                    "sequence",
                    "record game_id changed inside a game block",
                )
                if parsed_record["decision_id"] != str(current_count):
                    add_issue(
                        line_number,
                        game_id,
                        "sequence",
                        f"expected decision_id {current_count}, found {parsed_record['decision_id']}",
                    )
                current_count += 1

                stable_metadata = {
                    "seat_names": metadata.get("seat_names"),
                    "bot_styles": metadata.get("bot_styles"),
                }
                if current_metadata is None:
                    current_metadata = stable_metadata
                elif stable_metadata != current_metadata:
                    add_issue(
                        line_number,
                        game_id,
                        "sequence",
                        "game seat/style metadata changed within the game",
                    )

                if "terminal" in metadata:
                    if terminal is not None:
                        add_issue(
                            line_number,
                            game_id,
                            "sequence",
                            "terminal summary appears more than once in a game",
                        )
                    terminal = metadata["terminal"]
                    terminal_line = line_number
                if parsed_record["action"]["action"] == ActionType.WIN.value:
                    current_winning_seats.append(seat)
                observation = parsed_record["observation"]
                wind_observations.append((
                    seat,
                    observation["seat_wind"],
                    observation["round_wind"],
                    line_number,
                ))
            except (RecordError, TypeError, KeyError, ValueError) as error:
                category = error.category if isinstance(error, RecordError) else "format"
                add_issue(line_number, game_id, category, str(error))

    finish_game()
    if records_seen == 0:
        add_issue(None, None, "format", "dataset is empty")
    return ValidationReport(
        records=records_seen,
        games=games_seen,
        error_count=error_count,
        issues=tuple(issues),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="逐筆檢查 OpponentPool JSONL 是否符合 VLOG-BC 資料規範"
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s DATA_GEN_VERSION {DATA_GEN_VERSION}",
    )
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--max-errors", type=int, default=100)
    args = parser.parse_args(argv)

    try:
        report = validate_dataset(args.dataset, max_errors=args.max_errors)
    except (OSError, ValueError) as error:
        parser.exit(2, f"驗證無法執行：{error}\n")

    print(
        f"掃描 {report.records:,} 筆決策、{report.games:,} 局；"
        f"錯誤 {report.error_count:,}。"
    )
    for issue in report.issues:
        location = f"line {issue.line}" if issue.line is not None else "dataset"
        if issue.game_id:
            location += f", game {issue.game_id}"
        print(f"[{location}] {issue.category}: {issue.message}")
        print(f"  修正建議：{issue.recommendation}")
    if report.error_count > len(report.issues):
        print(f"其餘 {report.error_count - len(report.issues):,} 個錯誤未列出。")
    if report.valid:
        print(
            f"通過：動作皆屬於合法清單，觀測編碼為 {FEATURE_SIZE} 維，"
            f"規則版本 {RULESET_VERSION}、資料生成版本 {DATA_GEN_VERSION}，"
            "且每局都有完整結算。"
        )
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
