"""重跑同一個 batch-id 時，舊 JSONL 不能被接續寫入（會造成 event_id 重複）。

執行方式（專案根目錄）：
    python -m tests.test_archive_logs
或
    python -m pytest tests/test_archive_logs.py -v
"""

from src.common.events import EventSource, EventType, create_event
from src.common.logger import AppLogger
from src.control.replay import check_order, load_events
from test_interface.live_game import archive_old_logs
from tests._runner import run_module


def _write(folder, game_id):
    with AppLogger(log_dir=str(folder), game_id=game_id) as logger:
        logger.log_event(create_event(
            event_id="run_0001", game_id=game_id,
            event_type=EventType.SYSTEM_INFO, source=EventSource.INTEGRATION,
        ))


def test_appending_twice_breaks_order_check(tmp_path):
    _write(tmp_path, "b_g01")
    _write(tmp_path, "b_g01")

    problems = check_order(load_events(tmp_path / "b_g01.jsonl"))
    assert any("重複" in p for p in problems)


def test_archive_then_rewrite_is_clean(tmp_path):
    _write(tmp_path, "b_g01")
    (tmp_path / "b_g01.game.json").write_text("{}", encoding="utf-8")
    (tmp_path / "b_g01_pause_1_X.png").write_bytes(b"png")
    _write(tmp_path, "b_g02")  # 別局不能被動到

    moved = archive_old_logs(str(tmp_path), "b_g01", stamp="S")
    assert sorted(moved) == [
        "b_g01.game.json.S.bak", "b_g01.jsonl.S.bak", "b_g01_pause_1_X.png.S.bak",
    ]
    assert not (tmp_path / "b_g01.jsonl").exists()
    assert (tmp_path / "b_g02.jsonl").exists()

    _write(tmp_path, "b_g01")
    assert check_order(load_events(tmp_path / "b_g01.jsonl")) == []


def test_nothing_to_archive(tmp_path):
    assert archive_old_logs(str(tmp_path), "b_g01") == []
    assert archive_old_logs(str(tmp_path / "missing"), "b_g01") == []


if __name__ == "__main__":
    run_module(globals(), "test_archive_logs")