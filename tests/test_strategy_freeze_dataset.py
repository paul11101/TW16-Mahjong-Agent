import json

import pytest

from src.strategy import freeze_dataset as release
from src.strategy.dataset_builder import write_dataset
from src.strategy.generate_dataset import generate_records


@pytest.fixture
def source(tmp_path, monkeypatch):
    # 用兩筆真實模擬決策測試凍結流程，正式版門檻為十萬筆
    monkeypatch.setattr(release, "MIN_RECORDS", 2)
    path = tmp_path / "day4.jsonl"
    write_dataset(generate_records(2), path)
    return path


def test_freeze_keeps_independent_copy(source):
    folder = release.freeze_dataset(source)
    assert (folder / "decisions.jsonl").read_bytes() == source.read_bytes()

    # 移除測試用來源檔後，凍結副本仍能獨立驗證
    source.unlink()
    manifest = release.verify_dataset(folder)
    assert manifest["records"] == 2
    assert manifest["dataset_version"] == "v1"


def test_freeze_refuses_existing_version(source):
    folder = release.freeze_dataset(source)
    source.write_text("changed", encoding="utf-8")
    with pytest.raises(FileExistsError):
        release.freeze_dataset(source)
    assert release.verify_dataset(folder)["records"] == 2


def test_too_few_records_leave_no_release(source, monkeypatch):
    monkeypatch.setattr(release, "MIN_RECORDS", 3)
    with pytest.raises(ValueError, match="found 2"):
        release.freeze_dataset(source)
    assert not (source.parent / "v1").exists()


@pytest.mark.parametrize("target", ["decisions.jsonl", "manifest.json"])
def test_verify_detects_changes(source, target):
    folder = release.freeze_dataset(source)
    path = folder / target

    if target == "decisions.jsonl":
        # 對調兩行後，筆數與檔案大小都相同，但 SHA-256 會改變
        lines = path.read_bytes().splitlines(keepends=True)
        path.write_bytes(b"".join(reversed(lines)))
    else:
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest["records"] += 1
        path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="不一致"):
        release.verify_dataset(folder)