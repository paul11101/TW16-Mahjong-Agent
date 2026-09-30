"""測試介面 app 的控制閘門（不需要 httpx，直接呼叫 endpoint 函式）。

執行方式（專案根目錄）：
    python -m tests.test_app
或
    python -m pytest tests/test_app.py -v
"""

import tempfile

from test_interface import app as app_module


def _fresh(log_dir: str) -> None:
    app_module.LOG_DIR = log_dir
    app_module.reset_agent()


def test_tile_label():
    assert app_module.tile_label(0) == "一萬"
    assert app_module.tile_label(17) == "九筒"
    assert app_module.tile_label(18) == "一條"
    assert app_module.tile_label(27) == "東"
    assert app_module.tile_label(33) == "白"


def test_state_hand_has_16_plus_drawn_tiles(tmp_path):
    _fresh(str(tmp_path))
    state = app_module.get_state()

    assert state["control_state"] == "ready"
    assert len(state["hand"]) == 17
    assert state["hand"][0]["name"] == "一萬"


def test_run_allowed_when_ready(tmp_path):
    _fresh(str(tmp_path))
    result = app_module.run_test_agent()

    assert result["success"] is True
    assert result["receipt"]["ui_action_executed"] is True


def test_pause_blocks_run_and_resume_allows(tmp_path):
    _fresh(str(tmp_path))

    assert app_module.pause_agent()["control_state"] == "paused"
    blocked = app_module.run_test_agent()
    assert blocked.status_code == 409

    assert app_module.resume_agent()["control_state"] == "ready"
    assert app_module.run_test_agent()["success"] is True


def test_stop_blocks_run_until_reset(tmp_path):
    _fresh(str(tmp_path))

    assert app_module.stop_agent()["control_state"] == "stopped"
    # 停止後 resume 不能復原
    assert app_module.resume_agent()["control_state"] == "stopped"
    assert app_module.run_test_agent().status_code == 409

    assert app_module.reset_agent()["control_state"] == "ready"
    assert app_module.run_test_agent()["success"] is True


if __name__ == "__main__":
    from pathlib import Path

    with tempfile.TemporaryDirectory() as d:
        base = Path(d)
        test_tile_label()
        test_state_hand_has_16_plus_drawn_tiles(base / "a")
        test_run_allowed_when_ready(base / "b")
        test_pause_blocks_run_and_resume_allows(base / "c")
        test_stop_blocks_run_until_reset(base / "d")

    print("✅ test_app：5 項測試全部通過")