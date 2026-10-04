"""W2 最小串接測試：假 GameState → 策略 → 點擊 → 回執 → JSONL。

執行方式（專案根目錄）：
    python -m tests.test_agent_runner
或
    python -m pytest tests/test_agent_runner.py -v
"""

import json
import tempfile
from pathlib import Path

from test_interface.agent_runner import (
    FAKE_HAND_START_X,
    FAKE_HAND_Y,
    FakeMouse,
    run_agent,
)


def test_run_agent_success(tmp_path):
    result = run_agent(log_dir=str(tmp_path), game_id="t_success")

    assert result["success"] is True
    assert result["observation"] is not None
    assert len(result["observation"]["hand"]) == 17
    assert result["decision"]["success"] is True
    assert result["decision"]["action"]["type"] == "discard"
    assert result["execution"]["success"] is True
    assert result["receipt"]["success"] is True
    assert result["receipt"]["ui_action_executed"] is True
    # W2 尚未做操作後畫面驗證
    assert result["receipt"]["state_verified"] is False


def test_run_agent_clicks_expected_point(tmp_path):
    mouse = FakeMouse()
    result = run_agent(log_dir=str(tmp_path), game_id="t_click", mouse=mouse)

    # baseline 打第一個合法棄牌 = 牌 0，排序後在第 0 位
    assert result["decision"]["action"]["tile"] == 0
    assert mouse.clicks == [(FAKE_HAND_START_X, FAKE_HAND_Y)]


def test_run_agent_writes_jsonl(tmp_path):
    run_agent(log_dir=str(tmp_path), game_id="t_log")

    lines = (tmp_path / "t_log.jsonl").read_text(encoding="utf-8").splitlines()
    types = [json.loads(line)["event_type"] for line in lines]

    assert types[0] == "game_started"
    assert types[-1] == "game_stopped"
    for expected in (
        "state_updated",
        "legal_actions_generated",
        "decision_made",
        "action_completed",
    ):
        assert expected in types


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as d:
        base = Path(d)
        test_run_agent_success(base / "a")
        test_run_agent_clicks_expected_point(base / "b")
        test_run_agent_writes_jsonl(base / "c")

    print("✅ test_agent_runner：3 項測試全部通過")