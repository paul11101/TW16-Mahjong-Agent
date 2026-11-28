"""W10：策略比較（compare_reports、strategy_version、/api/compare）測試。

    python -m tests.test_compare_reports
"""

import pytest

from src.control.batch import aggregate, batch_strategy_version, compare_reports, save_report
from src.control.util import atomic_write_json
from test_interface import app as app_module
from test_interface.dashboard_page import DASHBOARD_HTML
from tests._runner import run_module


def _row(game_id, winner, result):
    return {
        "game_id": game_id, "finished": True, "interventions": 0, "ui_actions": 10, "ui_success": 10,
        "latencies_ms": [100.0, 200.0], "winner": winner, "result": result,
    }


def _report(batch_id, winners):
    rows = [_row(f"{batch_id}_g{i}", w, "win" if w is not None else "draw") for i, w in enumerate(winners)]
    return aggregate(batch_id, rows)


def test_compare_reports_rates_and_diff():
    a = _report("a", [0, None]).to_dict()
    b = _report("b", [2, 2]).to_dict()
    rows = {r["name"]: r for r in compare_reports(a, b)}

    assert rows["Agent 胡牌率"]["a"] == 0.5 and rows["Agent 胡牌率"]["b"] == 0.0
    assert rows["Agent 胡牌率"]["diff"] == pytest.approx(-0.5)
    assert rows["流局率"]["diff"] == pytest.approx(-0.5)
    assert rows["UI 動作數"]["diff"] == 0 and rows["同步動作確認 p95"]["unit"] == "ms"


def test_compare_reports_missing_values_have_no_diff():
    rows = compare_reports({"games": 0}, {"games": 0})
    assert all(r["diff"] is None for r in rows if r["unit"] == "ratio")


def test_batch_strategy_version(tmp_path):
    atomic_write_json(tmp_path / "b_g01.game.json", {"steps": [{"detail": {}}, {"detail": {"strategy_version": "model_x"}}]})
    atomic_write_json(tmp_path / "c_g01.game.json", {"steps": [{"detail": {}}]})
    (tmp_path / "d_g01.game.json").write_text("{壞", encoding="utf-8")

    assert batch_strategy_version(tmp_path, "b") == "model_x"
    assert batch_strategy_version(tmp_path, "c") is None
    assert batch_strategy_version(tmp_path, "d") is None
    assert batch_strategy_version(tmp_path, "nope") is None


def test_compare_endpoint(tmp_path):
    old = app_module.LOG_DIR
    app_module.LOG_DIR = str(tmp_path)
    try:
        save_report(tmp_path / "a.batch.json", _report("a", [0, None]))
        save_report(tmp_path / "b.batch.json", _report("b", [2, 2]))
        atomic_write_json(tmp_path / "b_g01.game.json", {"steps": [{"detail": {"strategy_version": "model_x"}}]})

        data = app_module.compare("a", "b")
        assert data["a"]["strategy_version"] is None and data["b"]["strategy_version"] == "model_x"
        assert any(r["name"] == "Agent 胡牌率" for r in data["rows"])

        assert app_module.compare("a", "nope").status_code == 404
        assert app_module.compare("..", "b").status_code == 404
        assert app_module.compare("a b", "b").status_code == 404
    finally:
        app_module.LOG_DIR = old


def test_dashboard_has_compare_section():
    assert "/api/compare" in DASHBOARD_HTML and 'id="cmpA"' in DASHBOARD_HTML and 'id="cmp"' in DASHBOARD_HTML


if __name__ == "__main__":
    run_module(globals(), "test_compare_reports")