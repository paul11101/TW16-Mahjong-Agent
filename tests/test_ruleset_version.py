import json
from dataclasses import replace

import pytest

from scripts.generate_batch_data import iter_game_records
from src.rules.opponent_pool import OpponentPool
from src.rules.rule import RULESET_VERSION, RulesetConfig
from src.strategy.dataset_builder import write_dataset
from src.strategy.generate_dataset import generate_records
from src.strategy.ruleset_validation import validate_ruleset_file
from src.strategy.versioned_dataset import (
    generate_versioned_dataset,
    validate_versioned_dataset,
    write_versioned_dataset,
)


def test_rules_config_uses_frozen_ruleset_version():
    assert RulesetConfig().ruleset_version == RULESET_VERSION


@pytest.mark.parametrize("version_field", ["rule_version", "ruleset_version"])
def test_dataset_validator_rejects_mismatched_version(tmp_path, version_field):
    source = tmp_path / "source.jsonl"
    write_dataset(generate_records(1), source)
    row = json.loads(source.read_text(encoding="utf-8"))
    row[version_field] = "outdated-rules"
    invalid = tmp_path / "invalid.jsonl"
    invalid.write_text(json.dumps(row) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="line 1:"):
        validate_versioned_dataset(invalid)


def test_dataset_validator_rejects_missing_version(tmp_path):
    source = tmp_path / "source.jsonl"
    write_dataset(generate_records(1), source)
    row = json.loads(source.read_text(encoding="utf-8"))
    del row["rule_version"]
    invalid = tmp_path / "missing.jsonl"
    invalid.write_text(json.dumps(row) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="line 1: ruleset_version is required"):
        validate_versioned_dataset(invalid)


def test_dataset_read_validation_checks_all_versions_at_open(tmp_path):
    source = tmp_path / "source.jsonl"
    write_dataset(generate_records(2), source)
    rows = source.read_text(encoding="utf-8").splitlines()
    row = json.loads(rows[1])
    row["rule_version"] = "outdated-rules"
    rows[1] = json.dumps(row)
    invalid = tmp_path / "invalid.jsonl"
    invalid.write_text("\n".join(rows) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="line 2: .*mismatch"):
        validate_ruleset_file(invalid)


def test_dataset_read_validation_rejects_missing_version_at_open(tmp_path):
    source = tmp_path / "source.jsonl"
    write_dataset(generate_records(1), source)
    row = json.loads(source.read_text(encoding="utf-8"))
    del row["rule_version"]
    invalid = tmp_path / "missing.jsonl"
    invalid.write_text(json.dumps(row) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="line 1: ruleset_version is required"):
        validate_ruleset_file(invalid)


def test_dataset_writer_blocks_record_with_non_frozen_rule_version(tmp_path):
    record = next(generate_records(1))
    invalid_record = replace(record, rule_version="outdated-rules")

    with pytest.raises(ValueError, match="rule_version mismatch"):
        write_versioned_dataset([invalid_record], tmp_path / "invalid.jsonl")
    assert not (tmp_path / "invalid.jsonl").exists()


def test_versioned_generator_writes_validated_data(tmp_path):
    output = tmp_path / "generated.jsonl"

    count = generate_versioned_dataset(output, limit=1, start_seed=15)

    assert count > 0
    assert validate_versioned_dataset(output) == count


def test_batch_generation_rejects_non_frozen_rules_before_simulating():
    config = RulesetConfig(ruleset_version=f"{RULESET_VERSION}-changed")
    with pytest.raises(ValueError, match="ruleset_version mismatch"):
        next(iter_game_records(1, 0, config, OpponentPool({"balanced": 1})))
