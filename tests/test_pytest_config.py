"""pytest.ini 與 conftest 的設定檢查。

執行方式（專案根目錄）：
    python -m tests.test_pytest_config
或
    python -m pytest tests/test_pytest_config.py -v
"""

import configparser
from pathlib import Path

from tests._runner import run_module
from tests.conftest import has_vision_data

ROOT = Path(__file__).resolve().parent.parent


def _ini():
    parser = configparser.ConfigParser()
    parser.read(ROOT / "pytest.ini", encoding="utf-8")
    return parser["pytest"]


def test_pytest_ini_settings():
    ini = _ini()
    assert ini["pythonpath"] == "."
    assert ini["testpaths"] == "tests"


def test_markers_registered():
    markers = _ini()["markers"]
    assert "slow:" in markers and "needs_data:" in markers


def test_has_vision_data_returns_bool():
    assert isinstance(has_vision_data(), bool)


if __name__ == "__main__":
    run_module(globals(), "test_pytest_config")