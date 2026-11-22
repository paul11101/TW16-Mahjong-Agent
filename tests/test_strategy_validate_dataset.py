import json

import pytest

from src.strategy.dataset_builder import write_dataset
from src.strategy.generate_dataset import generate_records
from src.strategy.validate_dataset import validate_dataset


# 用真實生成器產生兩筆，測試直接讀取 Day 2 寫出的格式
@pytest.fixture(scope="module")
def rows(tmp_path_factory):
    path = tmp_path_factory.mktemp("samples") / "source.jsonl"
    write_dataset(generate_records(2), path)
    return path.read_text(encoding="utf-8").splitlines()


def test_valid_dataset_and_minimum(tmp_path, rows):
    path = tmp_path / "data.jsonl"
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    assert validate_dataset(path, min_records=2) == 2

    with pytest.raises(ValueError, match="expected at least 3 records, found 2"):
        validate_dataset(path, min_records=3)


# 故意把第二筆的標籤改成遮罩禁止的動作，錯誤應指出第 2 行
def test_illegal_label(tmp_path, rows):
    data = json.loads(rows[1])
    data["action_index"] = data["action_mask"].index(0)
    path = tmp_path / "data.jsonl"
    path.write_text(rows[0] + "\n" + json.dumps(data), encoding="utf-8")

    with pytest.raises(ValueError, match="line 2: .*legal action"):
        validate_dataset(path)


@pytest.mark.parametrize("problem", ["duplicate", "invalid_json", "blank"])
def test_bad_second_line(tmp_path, rows, problem):
    bad_line = {"duplicate": rows[0], "invalid_json": "{", "blank": ""}[problem]
    path = tmp_path / "data.jsonl"
    path.write_text(rows[0] + "\n" + bad_line + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="line 2:"):
        validate_dataset(path)


def test_empty_dataset(tmp_path):
    path = tmp_path / "empty.jsonl"
    path.touch()
    with pytest.raises(ValueError, match="found 0"):
        validate_dataset(path)