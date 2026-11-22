import argparse
import json
from pathlib import Path
from shutil import copyfile
from tempfile import TemporaryDirectory

from src.control.release import sha256_file
from src.strategy.training_sample import SCHEMA_VERSION
from src.strategy.validate_dataset import validate_dataset

DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "strategy"
SOURCE = DATA_DIR / "decisions_10000_100000.jsonl"
VERSION = "v1"
MIN_RECORDS = 100_000
DATA_FILE = "decisions.jsonl"
MANIFEST = "manifest.json"


# 沿用 Day 4 檢查每筆資料，另記下整份檔案的 SHA-256
def describe_dataset(path: Path) -> dict:
    return {
        "dataset_version": VERSION,
        "schema_version": SCHEMA_VERSION,
        "file": path.name,
        "records": validate_dataset(path, min_records=MIN_RECORDS),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def freeze_dataset(source: Path) -> Path:
    release = source.parent / VERSION
    if release.exists():
        raise FileExistsError(f"{release} 已存在，可執行 verify 核對版本")
    if not source.is_file():
        raise FileNotFoundError(f"找不到 Day 4 資料集：{source}")

    # 先準備副本，資料與清單都完成後才建立正式的 v1 資料夾
    with TemporaryDirectory(dir=source.parent) as temp:
        staged = Path(temp) / VERSION
        staged.mkdir()
        data = staged / DATA_FILE
        copyfile(source, data)

        manifest = describe_dataset(data)
        if sha256_file(source) != manifest["sha256"]:
            raise ValueError("凍結期間來源檔案已變動，請重新執行")

        (staged / MANIFEST).write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
        )
        staged.rename(release)
    return release


# 重新檢查凍結副本，並與當初保存的清單比對
def verify_dataset(release: Path) -> dict:
    saved = json.loads((release / MANIFEST).read_text(encoding="utf-8"))
    actual = describe_dataset(release / DATA_FILE)
    if actual != saved:
        raise ValueError("凍結副本與 manifest.json 不一致")
    return actual


def main() -> None:
    parser = argparse.ArgumentParser(description="凍結或驗證策略資料集 v1")
    parser.add_argument("command", nargs="?", choices=("freeze", "verify"), default="freeze")
    args = parser.parse_args()

    try:
        if args.command == "freeze":
            print(f"已凍結資料集：{freeze_dataset(SOURCE)}")
        else:
            manifest = verify_dataset(DATA_DIR / VERSION)
            print(f"v1 驗證通過，共 {manifest['records']:,} 筆")
            print(f"SHA-256：{manifest['sha256']}")
    except (OSError, ValueError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()