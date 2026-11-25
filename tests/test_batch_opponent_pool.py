import json

from scripts.generate_batch_data import generate_batch_data
from src.rules.opponent_pool import OpponentPool
from src.strategy.data_generation_version import DATA_GEN_VERSION


def test_batch_records_each_seat_style_and_ruleset_version(tmp_path):
    files = generate_batch_data(
        1,
        1,
        57,
        tmp_path,
        opponent_pool=OpponentPool({"balanced": 1}),
    )
    records = [
        json.loads(line)
        for line in files[0].read_text(encoding="utf-8").splitlines()
    ]

    assert records
    game_styles = records[0]["game_metadata"]["bot_styles"]
    assert game_styles == ["balanced"] * 4
    assert records[0]["game_metadata"]["seat_names"] == [
        "east", "south", "west", "north",
    ]
    for record in records:
        assert record["ruleset_version"] == "1.0.0"
        assert record["data_gen_version"] == DATA_GEN_VERSION
        assert record["game_metadata"]["bot_styles"] == game_styles
        assert record["bot_style"] == game_styles[record["observation"]["seat"]]
