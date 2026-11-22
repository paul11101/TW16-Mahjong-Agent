import json
from itertools import takewhile

import pytest
import torch

from src.control.release import sha256_file
from src.strategy.dataset_builder import write_dataset
from src.strategy.export_vlog_bc import export_bc
from src.strategy.generate_dataset import generate_records
from src.strategy.train_vlog_bc import train_bc
from src.strategy.vlog_executor import VlogBCExecutor


@pytest.fixture(scope="module")
def checkpoint(tmp_path_factory):
    # 用四個完整模擬對局跑 Day 4，取得實際更新過權重的 checkpoint
    folder = tmp_path_factory.mktemp("bc_export")
    data = folder / "decisions.jsonl"
    records = takewhile(lambda row: row.wall_seed < 104, generate_records(start_seed=100))
    write_dataset(records, data)
    return train_bc(data, folder / "runs", epochs=1, batch_size=32)


def test_release_matches_day4(checkpoint, tmp_path):
    destination = tmp_path / "bc_v1"
    model_file = export_bc(checkpoint, destination)
    saved = torch.load(checkpoint, map_location="cpu", weights_only=True)
    report = json.loads((destination / "training.json").read_text(encoding="utf-8"))

    assert model_file.name == report["model"] == "bc_v1.pt"
    assert report["model_sha256"] == sha256_file(model_file)
    for key in ("epoch", "config", "source", "history"):
        assert report[key] == saved[key]

    # 同一批牌面分別送進 Day 4 模型與正式模型，兩者應給出相同分數
    original = VlogBCExecutor().eval()
    original.load_state_dict(saved["model_state_dict"])
    deployed = torch.jit.load(str(model_file), map_location="cpu").eval()
    with torch.inference_mode():
        features = torch.zeros(2, 555, dtype=torch.float32)
        logits = deployed(features)
        assert logits.shape == (2, 125) and logits.dtype == torch.float32
        torch.testing.assert_close(logits, original(features))

    with pytest.raises(FileExistsError):
        export_bc(checkpoint, destination)


def test_wrong_schema_leaves_no_release(checkpoint, tmp_path):
    saved = torch.load(checkpoint, map_location="cpu", weights_only=True)
    saved["source"]["schema_version"] = "unknown"
    bad = tmp_path / "bad.pt"
    torch.save(saved, bad)

    destination = tmp_path / "bc_v1"
    with pytest.raises(ValueError, match="schema"):
        export_bc(bad, destination)
    assert not destination.exists()