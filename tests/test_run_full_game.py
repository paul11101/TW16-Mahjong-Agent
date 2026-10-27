"""W6 實機入口 run_full_game 的參數與匯入測試（不會真的點擊、不需要瀏覽器）。

執行方式（專案根目錄）：
    python -m tests.test_run_full_game
或
    python -m pytest tests/test_run_full_game.py -v
"""

from test_interface import run_full_game
from tests._runner import run_module


def test_parser_defaults():
    args = run_full_game.build_parser().parse_args([])

    assert args.seed == 1 and args.keep_game is False
    assert args.max_steps == 300 and args.poll == 0.2
    assert args.advance_timeout == 5.0 and args.pause_timeout == 120.0
    assert args.max_retries == 1 and args.no_verify is False  # 沿用共用參數
    assert args.title == "台灣16張麻將 Agent 測試介面"


def test_parser_overrides():
    args = run_full_game.build_parser().parse_args(
        ["--seed", "7", "--keep-game", "--no-verify", "--idle-timeout", "0", "--no-hotkeys"]
    )

    assert args.seed == 7 and args.keep_game and args.no_verify and args.no_hotkeys
    assert args.idle_timeout == 0


if __name__ == "__main__":
    run_module(globals(), "test_run_full_game")