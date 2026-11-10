"""pytest 共用設定：缺少 data/ 資料時，自動略過標記為 needs_data 的測試。"""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def has_vision_data() -> bool:
    raw, samples = ROOT / "data" / "raw", ROOT / "data" / "samples"
    return (
        raw.is_dir() and samples.is_dir()
        and any(raw.glob("*.png")) and any(samples.glob("*.png"))
    )


def pytest_collection_modifyitems(config, items):
    if has_vision_data():
        return
    skip = pytest.mark.skip(reason="缺少 data/raw 或 data/samples（data/ 被 gitignore，乾淨環境沒有）")
    for item in items:
        if "needs_data" in item.keywords:
            item.add_marker(skip)