import json
from collections import defaultdict
from dataclasses import dataclass
from random import Random
from torch.utils.data import Subset
from .dataset_loader import DecisionDataset
from .generate_dataset import generate_records

@dataclass(frozen=True)
class GameSplit:
    train: Subset
    val: Subset
    test: Subset
    excluded_game: str | None

def split_v1_by_game(dataset: DecisionDataset, seed: int = 42) -> GameSplit:
    groups = defaultdict(list)
    tail = None

    # 依局號收集每筆決策的列索引，讓同一局的決策一起分組
    with dataset.path.open("rb") as stream:
        for index, line in enumerate(stream):
            row = json.loads(line)
            if type(row.get("wall_seed")) is not int:
                raise ValueError(f"line {index + 1}: missing W8 wall_seed")

            groups[row["game_id"]].append(index)
            # W8 逐局遞增牌山種子，最大種子對應可能被截斷的尾局
            if tail is None or row["wall_seed"] > tail["wall_seed"]:
                tail = row


    if tail is None:
        raise ValueError("empty dataset")

    game_id = tail["game_id"]
    count = len(groups[game_id])
    matched = 0
    # 從尾局種子重播並多取一筆，檢查檔案是否在這局結束前停止寫入
    for record in generate_records(limit=count + 1, start_seed=tail["wall_seed"]):
        if record.game_id != game_id:
            break

        if (record.strategy_version, record.rule_version) != (tail["strategy_version"], tail["rule_version"]):
            raise ValueError("tail replay version mismatch")

        matched += 1

    excluded = None
    if matched < count:
        raise ValueError("tail game does not match W8 replay")

    # 多出的決策仍屬於尾局，切分時排除這局並記下局號
    if matched > count:
        excluded = game_id
        del groups[game_id]

    games = sorted(groups)
    if len(games) < 3:
        raise ValueError("at least 3 complete games are required")

    # 用固定種子打亂局號，驗證集和測試集各取約一成，至少各一局
    Random(seed).shuffle(games)
    holdout = max(1, (len(games) + 5) // 10)

    # 用列索引共用原始資料集，組內保留 JSONL 的順序
    def subset(ids: list[str]) -> Subset:
        return Subset(dataset, sorted(i for game in ids for i in groups[game]))

    return GameSplit(
        train=subset(games[2 * holdout:]),
        val=subset(games[:holdout]),
        test=subset(games[holdout:2 * holdout]),
        excluded_game=excluded,
    )