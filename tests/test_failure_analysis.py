"""W8 D2/D4 失敗分析工具測試（合成 logs，不需要瀏覽器）。

執行方式（專案根目錄）：
    python -m tests.test_failure_analysis
或
    python -m pytest tests/test_failure_analysis.py -v
"""

from src.control.batch import aggregate, failed_start_row, save_report
from src.control.failure_analysis import (
    analyze,
    format_analysis,
    latency_stats,
    load_game_records,
    main,
)
from src.control.util import atomic_write_json
from tests._runner import run_module


def _step(index, phase, *, success=True, error=None, latency=100.0, ui=True, retry=0, attempt=1):
    return {
        "index": index, "attempt": attempt, "phase": phase, "action_id": f"a{index}",
        "success": success, "skipped": False, "ui_action_executed": ui, "state_verified": success,
        "retry_count": retry, "latency_ms": latency, "error": error, "detail": {},
        "at": "x", "clicks": 1, "planned_clicks": 1,
    }


def _rows():
    good = {"game_id": "b_g01", "seed": 1, "finished": True, "reason": "game_over", "interventions": 0,
            "ui_actions": 2, "ui_success": 2, "error_codes": {}, "latencies_ms": [100.0, 300.0]}
    rough = {"game_id": "b_g02", "seed": 2, "finished": True, "reason": "game_over", "interventions": 1,
             "ui_actions": 2, "ui_success": 1, "error_codes": {"ACTION_TIMEOUT": 1}, "latencies_ms": [500.0, 1900.0]}
    return [good, rough, failed_start_row("b_g03", 3, "START_FAILED")]


def _records():
    return [
        {"game_id": "b_g01", "steps": [_step(0, "my_turn", latency=100.0), _step(1, "reaction", latency=300.0)]},
        {"game_id": "b_g02", "steps": [
            _step(0, "my_turn", latency=500.0),
            _step(1, "reaction", success=False, error="ACTION_TIMEOUT", latency=1900.0, retry=1),
        ]},
    ]


def test_latency_stats():
    assert latency_stats([]) == {"n": 0, "mean": None, "p50": None, "p95": None, "max": None}
    st = latency_stats([float(i) for i in range(1, 101)])
    assert st["n"] == 100 and st["p95"] == 95.0 and st["p50"] == 50.5 and st["max"] == 100.0
    assert latency_stats([None, 5.0])["n"] == 1


def test_analyze_finds_bad_games_failures_and_latency():
    batch = aggregate("b", _rows()).to_dict()
    result = analyze(batch, _records())

    assert [g["game_id"] for g in result["bad_games"]] == ["b_g02", "b_g03"]
    assert result["missing_records"] == ["b_g03"]
    assert result["error_counts"] == {"ACTION_TIMEOUT": 1}
    assert result["phase_error_counts"] == {"reaction:ACTION_TIMEOUT": 1}
    assert result["failed_steps"][0]["game_id"] == "b_g02"
    assert result["retried_steps"] == 1

    lat = result["latency"]
    assert lat["all"]["n"] == 4 and lat["all"]["p95"] == 1900.0
    assert lat["by_phase"]["my_turn"]["n"] == 2 and lat["by_phase"]["reaction"]["max"] == 1900.0
    assert result["p95_ok"] is True
    assert result["slowest"][0]["latency_ms"] == 1900.0


def test_p95_over_budget_is_reported():
    records = [{"game_id": "b_g01", "steps": [_step(0, "my_turn", latency=2500.0)]}]
    result = analyze(aggregate("b", _rows()[:1]).to_dict(), records)

    assert result["p95_ok"] is False
    assert "❌ 未達標" in format_analysis(result)


def test_no_latency_data():
    result = analyze(aggregate("b", _rows()[:1]).to_dict(), [])
    assert result["p95_ok"] is None and result["latency"]["all"]["n"] == 0


def test_load_game_records_skips_bad_files(tmp_path):
    atomic_write_json(tmp_path / "b_g01.game.json", _records()[0])
    (tmp_path / "b_g02.game.json").write_text("{壞", encoding="utf-8")
    atomic_write_json(tmp_path / "other_g01.game.json", _records()[1])  # 別批的不要讀

    assert [r["game_id"] for r in load_game_records(tmp_path, "b")] == ["b_g01"]


def test_main_writes_report(tmp_path):
    save_report(tmp_path / "b.batch.json", aggregate("b", _rows()))
    for rec in _records():
        atomic_write_json(tmp_path / f"{rec['game_id']}.game.json", rec)
    out = tmp_path / "out" / "analysis.txt"

    assert main([str(tmp_path), "--batch", "b", "--out", str(out)]) == 0
    text = out.read_text(encoding="utf-8")
    assert "ACTION_TIMEOUT" in text and "b_g02" in text and "p95" in text

    assert main([str(tmp_path)]) == 0  # 不給 --batch：用最新一批
    assert main([str(tmp_path), "--batch", "nope"]) == 1
    assert main([str(tmp_path / "empty")]) == 1


if __name__ == "__main__":
    run_module(globals(), "test_failure_analysis")