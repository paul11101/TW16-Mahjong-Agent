import math
from itertools import takewhile

import pytest
import torch
from torch import nn
from torch.utils.data import DataLoader

from src.strategy.dataset_builder import write_dataset
from src.strategy.generate_dataset import generate_records
from src.strategy.train_vlog_bc import run_epoch, train_bc
from src.strategy.vlog_executor import VlogBCExecutor


def test_metrics_count_forced_and_choice_decisions():
    # 第一筆只有一個合法動作，後兩筆可二選一，教師答案都是 0
    logits = torch.tensor([[4, 0, 5], [0, 1, 2], [2, 1, 0]], dtype=torch.float32)
    masks = torch.tensor([[1, 0, 0], [1, 1, 0], [1, 1, 0]], dtype=torch.bool)
    rows = [
        {"features": x, "action_mask": mask, "action_index": 0}
        for x, mask in zip(logits, masks)
    ]

    # Identity 直接回傳指定的分數，可以手算每個指標的預期值
    model = nn.Identity()
    result = run_epoch(model, DataLoader(rows, batch_size=2))

    assert result["samples"] == 3
    assert result["choice_samples"] == 2
    assert result["accuracy"] == pytest.approx(2 / 3)
    assert result["choice_accuracy"] == 0.5
    assert result["raw_illegal_rate"] == pytest.approx(2 / 3)
    assert result["illegal_rate"] == 0.0

    # 第一筆只有一個合法動作，交叉熵為零；三筆仍一起計入平均
    expected = (math.log1p(math.exp(1)) + math.log1p(math.exp(-1))) / 3
    assert result["loss"] == pytest.approx(expected)
    assert run_epoch(model, DataLoader(rows[:1]))["choice_accuracy"] is None


def test_training_updates_weights_and_saves_validation(tmp_path):
    # 取種子 100 到 103 的四個完整對局，串接資料生成、切分與訓練
    path = tmp_path / "decisions.jsonl"
    records = takewhile(lambda row: row.wall_seed < 104, generate_records(start_seed=100))
    written = write_dataset(records, path)

    # 與 train_bc 使用相同的初始權重，才能比對訓練前後的差異
    torch.manual_seed(42)
    initial = VlogBCExecutor().action_head[-1].weight.detach().clone()
    output = train_bc(path, tmp_path / "runs", epochs=2, batch_size=32)

    saved = torch.load(output, map_location="cpu", weights_only=True)
    sizes = saved["source"]["split_samples"]
    assert sum(sizes.values()) == written
    assert min(sizes.values()) > 0
    assert saved["epoch"] == 2
    assert len(saved["history"]) == 2

    for entry in saved["history"]:
        for phase in ("train", "val"):
            metrics = entry[phase]
            assert metrics["samples"] == sizes[phase]
            assert math.isfinite(metrics["loss"])
            assert metrics["illegal_rate"] == 0.0

    # 重新載入保存的模型，確認訓練確實更新了動作頭權重
    restored = VlogBCExecutor()
    restored.load_state_dict(saved["model_state_dict"])
    assert not torch.equal(restored.action_head[-1].weight.detach(), initial)