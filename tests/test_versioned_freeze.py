import json

import pytest

from src.strategy import freeze_dataset as freeze_module
from src.strategy.dataset_builder import write_dataset
from src.strategy.generate_dataset import generate_records
from src.strategy.versioned_dataset import (
    freeze_versioned_dataset,
    verify_versioned_dataset,
)


def test_version_checked_freeze_and_verify_use_existing_freezer(tmp_path, monkeypatch):
    monkeypatch.setattr(freeze_module, "MIN_RECORDS", 2)
    source = tmp_path / "source.jsonl"
    write_dataset(generate_records(2), source)

    release = freeze_versioned_dataset(source)
    manifest = verify_versioned_dataset(release)

    assert manifest["records"] == 2
    assert manifest["dataset_version"] == "v1"


def test_version_checked_freeze_rejects_bad_source_before_creating_release(tmp_path):
    source = tmp_path / "source.jsonl"
    write_dataset(generate_records(1), source)
    row = json.loads(source.read_text(encoding="utf-8"))
    row["rule_version"] = "outdated-rules"
    source.write_text(json.dumps(row) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="ruleset_version mismatch"):
        freeze_versioned_dataset(source)
    assert not (tmp_path / "v1").exists()
