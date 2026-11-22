import json

import pytest
import torch
from torch.utils.data import DataLoader

from src.strategy.dataset_builder import write_dataset
from src.strategy.dataset_loader import DecisionDataset
from src.strategy.dataset_split import split_v1_by_game
from src.strategy.generate_dataset import generate_records
from src.strategy.vlog_executor import VlogBCExecutor


@pytest.fixture(scope="module")
def source(tmp_path_factory):
    # 生成十個完整對局，再保留第十一局的第一筆決策。
    def records():
        for record in generate_records(start_seed=100):
            yield record
            if record.wall_seed == 110:
                return

    path = tmp_path_factory.mktemp("w9") / "decisions.jsonl"
    write_dataset(records(), path)
    return path


def test_split_keeps_whole_games(source, tmp_path):
    lines = source.read_bytes().splitlines(keepends=True)
    ids = [json.loads(line)["game_id"] for line in lines]
    split = split_v1_by_game(DecisionDataset(source))
    parts = (split.train, split.val, split.test)
    games = [{ids[i] for i in part.indices} for part in parts]

    # 十局分成 8/1/1，局號不重疊，每筆完整對局資料恰好出現一次。
    assert [len(group) for group in games] == [8, 1, 1]
    assert len(set.union(*games)) == 10
    assert split.excluded_game == ids[-1]
    assert sorted(i for part in parts for i in part.indices) == list(range(len(ids) - 1))

    # 移除殘局後，剛好完整的尾局應保留，相同種子的分組也應一致。
    clean = tmp_path / "complete.jsonl"
    clean.write_bytes(b"".join(lines[:-1]))
    again = split_v1_by_game(DecisionDataset(clean))
    assert again.excluded_game is None
    for first, second in zip(parts, (again.train, again.val, again.test)):
        assert first.indices == second.indices


def test_executor_uses_loader_batch(source):
    batch = next(iter(DataLoader(DecisionDataset(source), batch_size=4)))
    model = VlogBCExecutor()
    logits = model(batch["features"])
    assert logits.shape == (4, 125) and logits.dtype == torch.float32

    # 用教師答案檢查梯度能傳回 encoder，並確認選出的動作合法。
    masked = logits.masked_fill(~batch["action_mask"], float("-inf"))
    loss = torch.nn.functional.cross_entropy(masked, batch["action_index"])
    loss.backward()
    assert torch.isfinite(loss)
    assert model.encoder[0].weight.grad is not None
    assert batch["action_mask"].gather(1, masked.argmax(1, keepdim=True)).all()

    # 切到評估模式後，確認 TorchScript 與原模型對同一批牌面給出相同分數
    model.eval()
    with torch.no_grad():
        scripted = torch.jit.script(model)
        torch.testing.assert_close(scripted(batch["features"]), model(batch["features"]))