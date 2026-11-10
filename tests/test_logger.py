"""AppLogger.close() 會移除自己加的 console handler，長時間跑多局不累積。

執行方式（專案根目錄）：
    python -m tests.test_logger
或
    python -m pytest tests/test_logger.py -v
"""

import logging

from src.common.logger import AppLogger
from tests._runner import run_module


def _handlers(game_id):
    return logging.getLogger(f"mahjong_agent.{game_id}").handlers


def test_close_removes_console_handler(tmp_path):
    logger = AppLogger(log_dir=str(tmp_path), game_id="lg_a")
    assert len(_handlers("lg_a")) == 1

    logger.close()
    assert _handlers("lg_a") == []
    logger.close()  # 重複關閉不會出錯


def test_repeated_open_close_does_not_accumulate(tmp_path):
    for _ in range(5):
        with AppLogger(log_dir=str(tmp_path), game_id="lg_b") as logger:
            logger.info("x")
            assert len(_handlers("lg_b")) == 1
        assert _handlers("lg_b") == []


def test_second_logger_with_same_id_does_not_own_handler(tmp_path):
    first = AppLogger(log_dir=str(tmp_path), game_id="lg_c")
    second = AppLogger(log_dir=str(tmp_path), game_id="lg_c")
    assert len(_handlers("lg_c")) == 1

    second.close()
    assert len(_handlers("lg_c")) == 1  # 第二個沒有加過 handler，不能移掉第一個的

    first.close()
    assert _handlers("lg_c") == []


if __name__ == "__main__":
    run_module(globals(), "test_logger")