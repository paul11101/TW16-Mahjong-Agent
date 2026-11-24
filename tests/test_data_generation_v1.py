from pathlib import Path

from scripts.generate_batch_data import DATA_GEN_VERSION, load_config, main
from scripts.validate_dataset import (
    DATA_GEN_VERSION as VALIDATOR_DATA_GEN_VERSION,
    validate_dataset,
)
from src.opponent_pool import OpponentPool
from src.weighted_policy import BOT_STYLE_PRESETS


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OPPONENT_CONFIG = PROJECT_ROOT / "configs" / "opponent_pool_v1.json"


def test_v1_opponent_config_is_valid_and_reproducible():
    weights = load_config(OPPONENT_CONFIG)
    assert set(weights) == set(BOT_STYLE_PRESETS)

    pool = OpponentPool(weights)
    assert pool.sample_styles(20261125) == pool.sample_styles(20261125)


def test_exporter_and_validator_share_generation_version():
    assert DATA_GEN_VERSION == VALIDATOR_DATA_GEN_VERSION


def test_standard_cli_flow_generates_a_valid_dataset(tmp_path):
    output_dir = tmp_path / "generated"
    result = main([
        "--num-games",
        "1",
        "--batch-size",
        "1",
        "--base-seed",
        "20261125",
        "--output-dir",
        str(output_dir),
        "--opponent-pool-config",
        str(OPPONENT_CONFIG),
    ])

    assert result == 0
    files = list(output_dir.glob("*.jsonl"))
    assert len(files) == 1
    report = validate_dataset(files[0])
    assert report.valid, report.issues
