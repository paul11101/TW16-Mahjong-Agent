import json

import pytest
import torch
from torch.utils.data import DataLoader

from src.strategy.dataset_builder import write_dataset
from src.strategy.dataset_loader import DecisionDataset
from src.strategy.generate_dataset import generate_records


# 用專案的資料產生器建立三筆決策，讓測試讀取實際的 JSONL 格式
@pytest.fixture(scope="module")
def source(tmp_path_factory):
    path = tmp_path_factory.mktemp("decisions") / "decisions.jsonl"
    write_dataset(generate_records(limit=3), path)
    return path


def test_batches_match_jsonl(source):
    expected = [json.loads(line) for line in source.read_text(encoding="utf-8").splitlines()]
    dataset = DecisionDataset(source)
    assert len(dataset) == 3

    # 刻意改變取樣順序，最後一批只剩一筆。
    loader = DataLoader(dataset, batch_size=2, sampler=[2, 0, 1])
    first, last = loader
    assert first["features"].shape == (2, 555)
    assert first["features"].dtype == torch.float32
    assert first["action_mask"].shape == (2, 125)
    assert first["action_mask"].dtype == torch.bool
    assert first["action_index"].shape == (2,)
    assert first["action_index"].dtype == torch.long
    assert last["features"].shape == (1, 555)

    # 按取樣順序對回原始資料，確認牌面、遮罩與教師答案來自同一筆決策
    for batch, indices in ((first, [2, 0]), (last, [1])):
        for pos, index in enumerate(indices):
            row = expected[index]
            assert batch["game_id"][pos] == row["game_id"]
            assert batch["decision_id"][pos] == row["decision_id"]
            assert torch.equal(batch["features"][pos], torch.tensor(row["features"], dtype=torch.float32))
            assert batch["action_mask"][pos].tolist() == [bool(x) for x in row["action_mask"]]
            assert batch["action_index"][pos].item() == row["action_index"]


def test_rejects_illegal_label(source, tmp_path):
    lines = source.read_text(encoding="utf-8").splitlines()
    row = json.loads(lines[1])
    # 把第二筆的教師答案改成非法動作，確認錯誤訊息指出第 2 行
    row["action_index"] = row["action_mask"].index(0)
    path = tmp_path / "bad.jsonl"
    path.write_text(lines[0] + "\n" + json.dumps(row), encoding="utf-8")

    with pytest.raises(ValueError, match="line 2: .*legal action"):
        DecisionDataset(path)[1]


# 空檔案應在建立資料集時就被拒絕
def test_rejects_empty_file(tmp_path):
    path = tmp_path / "empty.jsonl"
    path.touch()
    with pytest.raises(ValueError, match="empty"):
        DecisionDataset(path)