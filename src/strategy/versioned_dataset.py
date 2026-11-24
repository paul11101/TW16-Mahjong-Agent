"""Version-checked entry points around the frozen dataset APIs."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Iterable

from src.strategy.dataset_builder import DecisionRecord, write_dataset
from src.strategy.generate_dataset import generate_records
from src.strategy.ruleset_validation import validate_ruleset_file, validate_ruleset_version
from src.strategy.validate_dataset import validate_dataset


def _checked_records(records: Iterable[DecisionRecord]) -> Iterable[DecisionRecord]:
    for record in records:
        validate_ruleset_version(record.rule_version, field_name="rule_version")
        yield record


def write_versioned_dataset(
    records: Iterable[DecisionRecord],
    output: str | Path,
) -> int:
    """Reject non-frozen records before the existing writer serializes them."""
    return write_dataset(_checked_records(records), output)


def generate_versioned_dataset(
    output: str | Path,
    *,
    limit: int = 10_000,
    start_seed: int = 10_000,
) -> int:
    return write_versioned_dataset(
        generate_records(limit=limit, start_seed=start_seed),
        output,
    )


def validate_versioned_dataset(
    path: str | Path,
    *,
    min_records: int = 1,
) -> int:
    validate_ruleset_file(path)
    return validate_dataset(path, min_records=min_records)


def load_versioned_dataset(path: str | Path):
    """Validate all JSONL rule versions before constructing the lazy dataset."""
    validate_ruleset_file(path)
    from src.strategy.dataset_loader import DecisionDataset

    return DecisionDataset(path)


def train_versioned_dataset(
    dataset: str | Path,
    runs_dir: str | Path,
    **training_options,
) -> Path:
    """Validate every row, then delegate to the unchanged VLOG-BC trainer."""
    validate_ruleset_file(dataset)
    from src.strategy.train_vlog_bc import train_bc

    return train_bc(Path(dataset), Path(runs_dir), **training_options)


def freeze_versioned_dataset(source: str | Path) -> Path:
    """Validate all rule versions, then use the unchanged freeze implementation."""
    validate_ruleset_file(source)
    from src.strategy.freeze_dataset import freeze_dataset

    return freeze_dataset(Path(source))


def verify_versioned_dataset(release: str | Path) -> dict:
    """Validate the frozen data file before delegating manifest verification."""
    from src.strategy.freeze_dataset import DATA_FILE, verify_dataset

    release = Path(release)
    validate_ruleset_file(release / DATA_FILE)
    return verify_dataset(release)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Use frozen-ruleset-checked VLOG-BC dataset operations"
    )
    commands = parser.add_subparsers(dest="command", required=True)

    generate_parser = commands.add_parser("generate")
    generate_parser.add_argument("output", type=Path)
    generate_parser.add_argument("--limit", type=int, default=10_000)
    generate_parser.add_argument("--start-seed", type=int, default=10_000)

    validate_parser = commands.add_parser("validate")
    validate_parser.add_argument("dataset", type=Path)
    validate_parser.add_argument("--min-records", type=int, default=1)

    train_parser = commands.add_parser("train")
    train_parser.add_argument("dataset", type=Path)
    train_parser.add_argument("runs_dir", type=Path)
    train_parser.add_argument("--epochs", type=int, default=3)
    train_parser.add_argument("--batch-size", type=int, default=128)
    train_parser.add_argument("--lr", type=float, default=0.001)
    train_parser.add_argument("--seed", type=int, default=42)

    freeze_parser = commands.add_parser("freeze")
    freeze_parser.add_argument("source", type=Path)

    verify_parser = commands.add_parser("verify")
    verify_parser.add_argument("release", type=Path)
    args = parser.parse_args()

    try:
        if args.command == "generate":
            written = generate_versioned_dataset(
                args.output,
                limit=args.limit,
                start_seed=args.start_seed,
            )
            print(f"已寫入 {written:,} 筆規則版本相符的資料：{args.output.resolve()}")
        elif args.command == "validate":
            count = validate_versioned_dataset(
                args.dataset,
                min_records=args.min_records,
            )
            print(f"驗證通過：{count:,} 筆，規則版本符合凍結版本。")
        elif args.command == "train":
            checkpoint = train_versioned_dataset(
                args.dataset,
                args.runs_dir,
                epochs=args.epochs,
                batch_size=args.batch_size,
                lr=args.lr,
                seed=args.seed,
            )
            print(f"訓練完成：{checkpoint.resolve()}")
        elif args.command == "freeze":
            release = freeze_versioned_dataset(args.source)
            print(f"已凍結版本檢查通過的資料集：{release.resolve()}")
        else:
            manifest = verify_versioned_dataset(args.release)
            print(
                f"凍結資料驗證通過：{manifest['records']:,} 筆，"
                f"SHA-256：{manifest['sha256']}"
            )
    except (OSError, ValueError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
