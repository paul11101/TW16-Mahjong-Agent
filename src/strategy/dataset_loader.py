import json
import torch
from pathlib import Path
from torch.utils.data import Dataset
from .training_sample import TrainingSample

# 將 JSONL 中的每筆教師決策對應到一個 PyTorch 資料集索引
class DecisionDataset(Dataset):
    def __init__(self, path: str | Path):
        self.path = Path(path).resolve()
        self.offsets: list[int] = []

        # 只記每行開頭的位元組位置，取樣時才讀取該行的牌局資料
        offset = 0
        with self.path.open("rb") as stream:
            for line in stream:
                self.offsets.append(offset)
                offset += len(line)


        if not self.offsets:
            raise ValueError("dataset is empty")

    def __len__(self) -> int:
        return len(self.offsets)

    def __getitem__(self, index: int) -> dict:
        # 單筆取樣沿用批次讀取，確保兩種方式回傳相同欄位
        return self.__getitems__([index])[0]

    def __getitems__(self, indices: list[int]) -> list[dict]:
        # 每批只開檔一次，依 DataLoader 指定的順序讀取決策
        rows = []
        with self.path.open("rb") as stream:
            for index in indices:
                stream.seek(self.offsets[index])
                try:
                    data = json.loads(stream.readline().decode("utf-8"))
                    # 沿用訓練樣本的驗證，檢查格式版本與教師動作是否合法
                    sample = TrainingSample.from_dict(data)
                    features = torch.tensor(sample.features, dtype=torch.float32)

                    # 原始數值即使有限，轉成 float32 後仍可能溢位
                    if not torch.isfinite(features).all():
                        raise ValueError("features exceed float32 range")
                except ValueError as error:
                    # 將取樣索引換算成 JSONL 行號，方便定位錯誤資料
                    line = (index if index >= 0 else len(self) + index) + 1
                    raise ValueError(f"line {line}: {error}") from error

                # 局號供後續依對局分組，遮罩標示合法動作，動作索引是教師答案
                rows.append({
                    "game_id": sample.game_id,
                    "decision_id": sample.decision_id,
                    "features": features,
                    "action_mask": torch.tensor(sample.action_mask, dtype=torch.bool),
                    "action_index": torch.tensor(sample.action_index, dtype=torch.long),
                })

        return rows
