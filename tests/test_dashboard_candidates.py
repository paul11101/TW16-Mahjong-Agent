"""W9：候選分數進 .game.json 與 dashboard 端點、模型延遲量測函式的測試。

執行方式（專案根目錄）：
    python -m tests.test_dashboard_candidates
或
    python -m pytest tests/test_dashboard_candidates.py -v
"""

from dataclasses import replace

from src.control.game_runner import PHASE_MY_TURN, PHASE_OVER, PHASE_WAITING
from src.control.model_adapter import ModelPolicy
from src.control.util import atomic_write_json
from src.strategy.interfaces import CandidateEvaluation
from test_interface import app as app_module
from test_interface import measure_decision as md
from test_interface.dashboard_page import DASHBOARD_HTML
from tests._runner import run_module
from tests.test_game_runner import make, result, seq, snap
from tests.test_model_adapter import RandomBackend


def test_step_detail_keeps_scorable_candidates():
    base = result()
    decision = replace(base.decision, candidate_evaluations=(
        CandidateEvaluation("discard_0", 0.7, scorable=True),
        CandidateEvaluation("discard_1", None),  # 沒有分數的不寫
    ))
    turn = replace(base, decision=decision)
    runner, _ = make(seq([snap(PHASE_MY_TURN, "a"), snap(PHASE_WAITING), snap(PHASE_OVER)]), lambda s: turn)
    runner.run()

    detail = runner.records[0].detail
    assert detail["candidates"] == [{"id": "discard_0", "score": 0.7}]
    assert detail["reason"] == "t"


def test_step_without_candidates_has_empty_list():
    runner, _ = make(seq([snap(PHASE_MY_TURN, "a"), snap(PHASE_WAITING), snap(PHASE_OVER)]), lambda s: result())
    runner.run()
    assert runner.records[0].detail["candidates"] == []


def test_game_record_endpoint(tmp_path):
    old = app_module.LOG_DIR
    app_module.LOG_DIR = str(tmp_path)
    try:
        atomic_write_json(tmp_path / "g1.game.json", {
            "game_id": "g1", "steps": [{"index": 0, "detail": {"candidates": [{"id": "a", "score": 1.0}]}}],
        })
        data = app_module.game_record("g1")
        assert data["steps"][0]["detail"]["candidates"][0]["id"] == "a"

        assert app_module.game_record("nope").status_code == 404
        assert app_module.game_record("..").status_code == 404
        assert app_module.game_record("a b").status_code == 404
    finally:
        app_module.LOG_DIR = old


def test_dashboard_page_has_steps_view():
    assert "/api/game_record/" in DASHBOARD_HTML and 'id="steps"' in DASHBOARD_HTML


def test_measure_policy_and_reset_stats():
    policy = ModelPolicy(RandomBackend(2), model_version="r")
    stats = md.measure_policy([1], policy)

    assert stats["all"]["n"] > 0 and policy.fallback_decisions == 0
    assert policy.model_decisions == stats["all"]["n"]

    policy.reset_stats()
    assert policy.model_decisions == 0 and policy.latencies_ms == [] and not policy.fallback_reasons


def test_step_detail_records_strategy_version():
    from src.control.game_runner import PHASE_MY_TURN, PHASE_OVER, PHASE_WAITING
    from tests.test_game_runner import make, result, seq, snap

    runner, _ = make(
        seq([snap(PHASE_MY_TURN, "a"), snap(PHASE_WAITING), snap(PHASE_OVER)]),
        lambda s: result(), strategy_version="model_x",
    )
    runner.run()
    assert runner.records[0].detail["strategy_version"] == "model_x"

    plain, _ = make(seq([snap(PHASE_MY_TURN, "a"), snap(PHASE_WAITING), snap(PHASE_OVER)]), lambda s: result())
    plain.run()
    assert "strategy_version" not in plain.records[0].detail


if __name__ == "__main__":
    run_module(globals(), "test_dashboard_candidates")