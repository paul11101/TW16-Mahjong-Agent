import json

import pytest

from scripts.generate_batch_data import generate_batch_data
from scripts.validate_dataset import validate_dataset
from src.rules.opponent_pool import OpponentPool


@pytest.fixture(scope="module")
def exported_game(tmp_path_factory):
    folder = tmp_path_factory.mktemp("vlog-export")
    output = generate_batch_data(
        1,
        1,
        73,
        folder,
        opponent_pool=OpponentPool({"balanced": 1}),
    )[0]
    return output.read_bytes().splitlines()


def _write_mutated_dataset(tmp_path, exported_game, change):
    records = [json.loads(line) for line in exported_game]
    change(records)
    path = tmp_path / "mutated.jsonl"
    path.write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
        encoding="utf-8",
    )
    return path


def test_generated_game_passes_export_consistency_validation(exported_game):
    assert exported_game
    records = [json.loads(line) for line in exported_game]
    terminal = records[-1]["game_metadata"]["terminal"]
    assert terminal["completed"] is True
    assert (
        terminal["decision_count"]
        == len(records)
    )


def test_validator_accepts_complete_generated_export(exported_game, tmp_path):
    dataset = tmp_path / "complete.jsonl"
    dataset.write_bytes(b"\n".join(exported_game) + b"\n")

    report = validate_dataset(dataset)

    assert report.valid
    assert report.records == len(exported_game)
    assert report.games == 1


def test_validator_rejects_chosen_action_outside_legal_actions(
    exported_game,
    tmp_path,
):
    path = _write_mutated_dataset(
        tmp_path,
        exported_game,
        lambda rows: rows[0]["action"].update(id="not_legal"),
    )

    report = validate_dataset(path)

    assert not report.valid
    assert any("not exactly present in legal_actions" in item.message for item in report.issues)


def test_validator_rejects_mismatched_ruleset_version(exported_game, tmp_path):
    path = _write_mutated_dataset(
        tmp_path,
        exported_game,
        lambda rows: rows[0].update(ruleset_version="0.9.0"),
    )

    report = validate_dataset(path)

    assert not report.valid
    assert any(item.category == "ruleset" for item in report.issues)


def test_validator_rejects_mismatched_data_generation_version(
    exported_game,
    tmp_path,
):
    path = _write_mutated_dataset(
        tmp_path,
        exported_game,
        lambda rows: rows[0].update(data_gen_version="2.0.0"),
    )

    report = validate_dataset(path)

    assert not report.valid
    assert any(item.category == "data_generation" for item in report.issues)


def test_validator_rejects_hidden_observation_fields(exported_game, tmp_path):
    path = _write_mutated_dataset(
        tmp_path,
        exported_game,
        lambda rows: rows[0]["observation"].update(wall=[1, 2, 3]),
    )

    report = validate_dataset(path)

    assert not report.valid
    assert any("unexpected fields" in item.message for item in report.issues)
    assert any("牌牆" in item.recommendation for item in report.issues)


def test_validator_rejects_missing_or_incomplete_game_summary(
    exported_game,
    tmp_path,
):
    def remove_terminal(rows):
        del rows[-1]["game_metadata"]["terminal"]

    path = _write_mutated_dataset(tmp_path, exported_game, remove_terminal)
    report = validate_dataset(path)

    assert not report.valid
    assert any("missing its terminal summary" in item.message for item in report.issues)


def test_validator_rejects_decision_sequence_gaps(exported_game, tmp_path):
    path = _write_mutated_dataset(
        tmp_path,
        exported_game,
        lambda rows: rows[1].update(decision_id="17"),
    )

    report = validate_dataset(path)

    assert not report.valid
    assert any("expected decision_id" in item.message for item in report.issues)


def test_validator_rejects_corrupted_settlement(exported_game, tmp_path):
    def corrupt_score(rows):
        rows[-1]["game_metadata"]["terminal"]["result"]["scores_dict"]["0"] += 1

    path = _write_mutated_dataset(tmp_path, exported_game, corrupt_score)
    report = validate_dataset(path)

    assert not report.valid
    assert any("scores_dict and score_delta" in item.message for item in report.issues)


def test_validator_tracks_multiple_win_actions_without_mutating_metadata(
    exported_game,
    tmp_path,
):
    def create_multiple_winners(rows):
        chosen = {}
        for row in rows:
            seat = row["observation"]["seat"]
            chosen.setdefault(seat, row)
        assert len(chosen) == 4

        for row in rows:
            if row["action"]["action"] == "win":
                row["action"] = next(
                    action
                    for action in row["legal_actions"]
                    if action["action"] != "win"
                )

        winners = list(chosen)[:2]
        for seat in winners:
            row = chosen[seat]
            win_action = {
                "id": f"validation-win-{seat}",
                "action": "win",
                "tile": None,
                "tiles": [],
                "kong_type": None,
            }
            row["legal_actions"].append(win_action)
            row["action"] = win_action

        result = rows[-1]["game_metadata"]["terminal"]["result"]
        result["win_type"] = "self_draw"
        result["winner_seats"] = winners
        result["loser_seat"] = None
        result["total_fans"] = None
        result["fan_details"] = []
        result["winner_fan_results"] = {
            str(seat): {
                "seat": seat,
                "total_fans": 0,
                "fan_details": [],
            }
            for seat in winners
        }

    path = _write_mutated_dataset(tmp_path, exported_game, create_multiple_winners)
    report = validate_dataset(path)

    assert report.valid, report.issues
