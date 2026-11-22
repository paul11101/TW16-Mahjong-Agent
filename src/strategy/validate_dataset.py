import argparse
import json
from pathlib import Path

from src.strategy.training_sample import TrainingSample


def validate_dataset(path: str | Path, *, min_records: int = 1) -> int:
    if type(min_records) is not int or min_records < 1:
        raise ValueError("min_records must be a positive integer")

    # 每次讀一行，只保留決策識別碼來檢查重複
    seen: set[tuple[str, str]] = set()
    with Path(path).open("rb") as stream:
        for line_number, line in enumerate(stream, start=1):
            try:
                data = json.loads(line.decode("utf-8"))
                # 沿用樣本驗證，確認教師標籤指向遮罩允許的動作
                sample = TrainingSample.from_dict(data)
            except ValueError as error:
                raise ValueError(f"line {line_number}: {error}") from error

            key = (sample.game_id, sample.decision_id)
            if key in seen:
                raise ValueError(f"line {line_number}: duplicate decision {key}")
            seen.add(key)

    count = len(seen)
    if count < min_records:
        raise ValueError(f"expected at least {min_records} records, found {count}")
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description="逐筆驗證 JSONL 決策資料集")
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--min-records", type=int, default=1)
    args = parser.parse_args()

    try:
        count = validate_dataset(args.dataset, min_records=args.min_records)
    except (OSError, ValueError) as error:
        parser.exit(1, f"驗證失敗：{error}\n")
    print(f"驗證通過：{count:,} 筆決策，所有標籤均為合法動作，無重複決策。")


if __name__ == "__main__":
    main()