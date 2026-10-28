"""W7 批次統計、點擊計數、儀表板的測試（假資料，不需要瀏覽器）。

執行方式（專案根目錄）：
    python -m tests.test_batch
或
    python -m pytest tests/test_batch.py -v
"""

import os
from dataclasses import replace
from types import SimpleNamespace

import pytest

from src.control.batch import (
    aggregate,
    check_targets,
    failed_start_row,
    format_report,
    list_game_records,
    list_reports,
    load_report,
    row_unattended,
    save_report,
)
from src.control.controller import AgentController
from src.control.game_runner import (
    PHASE_MY_TURN,
    PHASE_OVER,
    PHASE_REACTION,
    PHASE_WAITING,
    GameRunner,
)
from src.control.mouse import CountingMouse
from src.control.util import atomic_write_json
from test_interface import app as app_module
from test_interface.dashboard_page import DASHBOARD_HTML
from test_interface.fakes import FakeMouse
from tests._runner import run_module
from tests.helpers import FakeClock
from tests.test_game_runner import result as ok_result
from tests.test_game_runner import seq, snap


def _rows():
    good = {
        "game_id": "b_g01", "seed": 1, "finished": True, "reason": "game_over", "interventions": 0,
        "ui_actions": 10, "ui_success": 10, "failed": 0, "retries": 0, "physical_clicks": 10,
        "extra_clicks": 0, "error_codes": {}, "latencies_ms": [100.0, 200.0], "duration_s": 5.0,
    }
    rough = {
        "game_id": "b_g02", "seed": 2, "finished": True, "reason": "game_over", "interventions": 1,
        "ui_actions": 10, "ui_success": 9, "failed": 1, "retries": 1, "physical_clicks": 12,
        "extra_clicks": 1, "error_codes": {"ACTION_TIMEOUT": 1}, "latencies_ms": [300.0],
        "duration_s": 6.0, "page_match": False,
    }
    return [good, rough, failed_start_row("b_g03", 3, "START_FAILED")]


def test_row_unattended():
    good, rough, _ = _rows()
    assert row_unattended(good) is True
    assert row_unattended(rough) is False  # 有人工介入
    assert row_unattended({**good, "truth_ok": False}) is False
    assert row_unattended({**good, "order_ok": False}) is False
    assert row_unattended({**good, "finished": False}) is False


def test_aggregate_keeps_failures_in_denominator():
    report = aggregate("b", _rows(), requested=5)

    assert report.games == 3 and report.requested_games == 5
    assert report.finished_games == 2 and report.unattended_games == 1
    assert report.unattended_rate == pytest.approx(1 / 3)
    assert report.interventions == 2
    assert report.ui_actions == 20 and report.ui_success == 19
    assert report.ui_success_rate == pytest.approx(0.95)
    assert report.retries == 1 and report.failed_attempts == 1
    assert report.physical_clicks == 22 and report.extra_clicks == 1
    assert report.page_mismatch_games == 1
    assert report.error_codes == {"ACTION_TIMEOUT": 1, "START_FAILED": 1}
    assert report.latency_count == 3 and report.latency_p95_ms == 300.0  # 合併樣本再算
    assert report.duration_s == pytest.approx(11.0)
    assert all("latencies_ms" not in r for r in report.rows)


def test_aggregate_empty():
    report = aggregate("e", [])

    assert report.games == 0 and report.unattended_rate is None
    assert report.ui_success_rate is None and report.latency_p95_ms is None
    assert all(c["ok"] is None for c in check_targets(report))


def test_check_targets_and_format():
    report = aggregate("b", _rows())
    checks = {c["name"]: c for c in check_targets(report)}

    assert checks["無介入完成率"]["ok"] is False
    assert checks["操作成功率"]["ok"] is False and "1,000" in checks["操作成功率"]["note"]
    assert checks["重複點擊"]["ok"] is False
    assert checks["同步動作確認 p95"]["ok"] is True

    text = format_report(report)
    assert "批次 b" in text and "無介入完成率" in text and "❌" in text and "✅" in text


def test_save_load_and_list_reports(tmp_path):
    old, new = tmp_path / "b1.batch.json", tmp_path / "b2.batch.json"
    save_report(old, aggregate("b1", _rows()))
    save_report(new, aggregate("b2", _rows()))
    os.utime(old, (1000, 1000))  # b1 比較舊
    (tmp_path / "bad.batch.json").write_text("{壞", encoding="utf-8")

    assert load_report(old)["games"] == 3
    reports = list_reports(tmp_path)
    assert [r["batch_id"] for r in reports] == ["b2", "b1"]  # 新到舊，壞檔略過
    assert "targets" in reports[0]
    assert list_reports(tmp_path / "nothing") == []
    assert len(list_reports(tmp_path, limit=1)) == 1


def test_list_game_records(tmp_path):
    atomic_write_json(tmp_path / "g1.game.json", {
        "game_id": "g1", "complete": True, "saved_at": "x",
        "summary": {"finished": True, "reason": "game_over", "interventions": 0,
                    "ui_actions": 3, "ui_success": 3, "latency_p95_ms": 120.0},
        "steps": [{}, {}, {}],
    })
    atomic_write_json(tmp_path / "g2.game.json", {"game_id": "g2", "complete": False, "summary": None, "steps": []})

    records = {r["game_id"]: r for r in list_game_records(tmp_path)}
    assert set(records) == {"g1", "g2"}
    assert records["g1"]["steps"] == 3 and records["g1"]["finished"] is True
    assert records["g2"]["finished"] is None


# ------------------------------------------------------------------ 點擊計數

def _play(clicks, plan):
    mouse = CountingMouse(FakeMouse())
    controller = AgentController(game_id="g", mouse=mouse)
    controller.start()

    def turn(_snap):
        for _ in range(clicks):
            controller.click(5, 6)
        return replace(ok_result(), plan=plan)

    clock = FakeClock()
    runner = GameRunner(
        controller, game_id="g",
        observe_fn=seq([snap(PHASE_MY_TURN, "a"), snap(PHASE_WAITING), snap(PHASE_OVER)]),
        turn_fns={PHASE_MY_TURN: turn, PHASE_REACTION: turn},
        poll_interval=0.2, advance_timeout=5.0, idle_timeout=None, pause_timeout=1.0,
        clock=clock, sleep=clock.sleep,
    )
    return runner.run(), runner


def test_normal_click_has_no_extra_clicks():
    summary, runner = _play(1, SimpleNamespace())

    assert summary.physical_clicks == 1 and summary.extra_clicks == 0
    assert summary.latencies_ms == [100.0]
    assert runner.records[0].clicks == 1 and runner.records[0].planned_clicks == 1


def test_double_click_is_counted_as_extra():
    summary, _ = _play(2, SimpleNamespace())  # 計畫 1 次卻點了 2 次

    assert summary.physical_clicks == 2 and summary.extra_clicks == 1


def test_two_step_plan_allows_two_clicks():
    summary, runner = _play(2, SimpleNamespace(steps=(1, 2)))

    assert summary.extra_clicks == 0 and runner.records[0].planned_clicks == 2


def test_mouse_without_counter_reports_zero():
    controller = AgentController(game_id="g", mouse=FakeMouse())
    controller.start()
    clock = FakeClock()
    runner = GameRunner(
        controller, game_id="g",
        observe_fn=seq([snap(PHASE_MY_TURN, "a"), snap(PHASE_WAITING), snap(PHASE_OVER)]),
        turn_fns={PHASE_MY_TURN: lambda s: ok_result()},
        poll_interval=0.2, idle_timeout=None, pause_timeout=1.0, clock=clock, sleep=clock.sleep,
    )
    summary = runner.run()

    assert summary.physical_clicks == 0 and summary.extra_clicks == 0


# ------------------------------------------------------------------ 儀表板

def test_dashboard_endpoints(tmp_path):
    old = app_module.LOG_DIR
    app_module.LOG_DIR = str(tmp_path)
    try:
        save_report(tmp_path / "b.batch.json", aggregate("b", _rows()))
        atomic_write_json(tmp_path / "g.game.json", {
            "game_id": "g", "complete": True, "summary": {"finished": True}, "steps": [],
        })

        data = app_module.dashboard_data()
        assert data["reports"][0]["batch_id"] == "b"
        assert data["games"][0]["game_id"] == "g"
        assert app_module.dashboard() == DASHBOARD_HTML
        assert "/api/dashboard" in DASHBOARD_HTML
    finally:
        app_module.LOG_DIR = old


if __name__ == "__main__":
    run_module(globals(), "test_batch")