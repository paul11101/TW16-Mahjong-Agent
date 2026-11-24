import json
from pathlib import Path

import pytest

from scripts.generate_batch_data import (
    generate_batch_data,
    load_config,
    validate_positive_int,
)


def test_batch_data_writes_game_shards_with_required_fields(tmp_path):
    files = generate_batch_data(2, 1, 7, tmp_path)

    assert len(files) == 2
    records = []
    for path in files:
        assert path.name.endswith(".jsonl")
        for line in path.read_text(encoding="utf-8").splitlines():
            records.append(json.loads(line))

    assert records
    required = {"observation", "legal_actions", "action", "ruleset_version"}
    for record in records:
        assert required <= record.keys()
        observation = record["observation"]
        assert {"hand", "melds", "flowers", "discards", "round_wind", "seat_wind"} <= observation.keys()
        assert record["ruleset_version"]
        assert record["legal_actions"]


def test_json_config_and_validation(tmp_path):
    config = tmp_path / "batch.json"
    config.write_text(json.dumps({
        "num_games": 3,
        "batch_size": 2,
        "base_seed": 11,
        "output_dir": "data/test",
    }), encoding="utf-8")

    assert load_config(config)["base_seed"] == 11
    with pytest.raises(ValueError, match="positive"):
        validate_positive_int("num_games", 0)
