"""W10：turn_ms／decision_ms 記錄、failure_analysis 分段、perf_report 的測試。

    python -m tests.test_perf_report
"""

from src.control.batch import aggregate, save_report
from src.control.failure_analysis import analyze, format_analysis
from src.control.game_runner import PHASE_MY_TURN, PHASE_OVER, PHASE_WAITING
from src.control.perf_report import build_report, main
from src.control.util import atomic_write_json
from tests._runner import run_module
from tests.test_failure_analysis import _rows, _step
from tests.test_game_runner import make, result, seq, snap


def _records():
    return [{"game_id": "b_g01", "steps": [
        {**_step(0, "my_turn", latency=100.0), "turn_ms": 500.0, "decision_ms": 2.0,
         "detail": {"strategy_version": "model_x"}},
        {**_step(1, "reaction", latency=300.0), "turn_ms": 300.0, "decision_ms": 1.0, "detail": {}},
        {**_step(2, "reaction", success=False, ui=False), "skipped": True, "turn_ms": 9999.0, "decision_ms": 9999.0},
    ]}]


def test_runner_records_turn_and_decision_ms():
    observe = seq([snap(PHASE_MY_TURN, "a"), snap(PHASE_WAITING), snap(PHASE_OVER)])
    runner, _ = make(observe, lambda s: result(), decision_ms_fn=lambda: 3.5)
    runner.run()
    record = runner.records[0]
    assert record.decision_ms == 3.5 and record.turn_ms is not None and record.turn_ms >= 0

    plain, _ = make(seq([snap(PHASE_MY_TURN, "a"), snap(PHASE_WAITING), snap(PHASE_OVER)]), lambda s: result())
    plain.run()
    assert plain.records[0].decision_ms is None and plain.records[0].turn_ms is not None


def test_decision_ms_fn_errors_are_ignored():
    def boom():
        raise RuntimeError("計時壞了")

    runner, _ = make(seq([snap(PHASE_MY_TURN, "a"), snap(PHASE_WAITING), snap(PHASE_OVER)]),
                     lambda s: result(), decision_ms_fn=boom)
    summary = runner.run()
    assert summary.finished and runner.records[0].decision_ms is None


def test_analyze_has_turn_and_decision_stats_without_skipped():
    out = analyze(aggregate("b", _rows()[:1]).to_dict(), _records())
    lat = out["latency"]

    assert lat["turn"]["n"] == 2 and lat["turn"]["max"] == 500.0  # 略過的反應不算
    assert lat["decision"]["n"] == 2 and lat["decision"]["max"] == 2.0
    assert "整個回合" in format_analysis(out)


def test_old_records_without_new_fields_still_work():
    old = [{"game_id": "b_g01", "steps": [_step(0, "my_turn")]}]
    out = analyze(aggregate("b", _rows()[:1]).to_dict(), old)
    assert out["latency"]["turn"]["n"] == 0 and out["latency"]["all"]["n"] == 1


def test_build_report_and_main(tmp_path):
    save_report(tmp_path / "b.batch.json", aggregate("b", _rows()[:1]))
    for rec in _records():
        atomic_write_json(tmp_path / f"{rec['game_id']}.game.json", rec)

    text = build_report(tmp_path, ["b"])
    assert "model_x" in text and "策略決策" in text and "p95" in text

    out = tmp_path / "docs" / "report.md"
    assert main(["--log-dir", str(tmp_path), "--batch", "b", "--out", str(out)]) == 0
    assert "W10 整合性能報告" in out.read_text(encoding="utf-8")
    assert main(["--log-dir", str(tmp_path), "--batch", "nope", "--out", str(out)]) == 1


if __name__ == "__main__":
    run_module(globals(), "test_perf_report")