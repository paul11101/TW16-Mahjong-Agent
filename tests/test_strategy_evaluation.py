import argparse
import hashlib
import json
import platform
import subprocess
from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.strategy import evaluation
from src.strategy.action_policy import ActionPolicy
from src.strategy.evaluation import EvaluationCase, evaluate_cases
from src.strategy.interfaces import Decision
from tests.test_strategy_baseline_comparison import FIXED_HANDS, make_discard_actions, make_observation
from tests.test_strategy_reaction_comparison import CASES

ROOT = Path(__file__).resolve().parents[1]


# 重用四組棄牌與八組反應牌例，不新增另一套評分演算法
def build_cases():
    cases = [
        EvaluationCase(
            case["name"], make_observation(case["hand"]),
            tuple(make_discard_actions(case["hand"])), f"discard_{case['expected_discard']}",
        )
        for case in FIXED_HANDS
    ]
    expected = {
        "win": "win_3", "chi": "chi_3_4_5", "pong": "pong_33", "pass": "pass",
        "ming_kong": "kong_33", "an_kong": "kong_33", "jia_kong": "kong_33", "low_wall": "pass",
    }
    for name, action_id in expected.items():
        obs, actions = CASES[name]
        cases.append(EvaluationCase(name, obs, tuple(actions), action_id))
    return tuple(cases)


# Git 不可用時保持未知，不影響固定牌例評測
def git_value(*args):
    try:
        return subprocess.run(
            ["git", *args], cwd=ROOT, capture_output=True, text=True,
            check=True, timeout=5,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None


# 記錄本機內容雜湊，避免把未提交修改誤認成 GitHub 版本
def source_digest():
    digest = hashlib.sha256()
    for folder in ("src", "tests"):
        for path in sorted((ROOT / folder).rglob("*.py")):
            digest.update(path.relative_to(ROOT).as_posix().encode("utf-8") + b"\0")
            digest.update(path.read_bytes() + b"\0")
    return digest.hexdigest()


def main(argv=None):
    parser = argparse.ArgumentParser(description="Baseline 固定牌例評測摘要")
    parser.add_argument("--repeats", type=int, default=10)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    cases = build_cases()
    report = evaluate_cases(ActionPolicy(), cases, repeats=args.repeats)
    now = datetime.now(timezone.utc)
    status = git_value("status", "--porcelain")
    fixtures = json.dumps([asdict(case) for case in cases], sort_keys=True, ensure_ascii=False)
    report["metadata"] = {
        "created_at": now.isoformat(),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "git_commit": git_value("rev-parse", "HEAD"),
        "git_dirty": None if status is None else bool(status),
        "source_sha256": source_digest(),
        "cases_sha256": hashlib.sha256(fixtures.encode("utf-8")).hexdigest(),
    }
    report["limitations"] = ["固定牌例回歸，不提供整局勝率、放槍率或平均淨得分。"]
    output = args.output or ROOT / "logs" / f"baseline_{now:%Y%m%d_%H%M%S_%f}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")

    summary = report["summary"]
    print(f"策略：{report['strategy_version']}")
    print(f"牌例：{summary['passed_cases']}/{summary['cases']} 通過")
    print(f"預期動作：{summary['expected_matches']}/{summary['attempts']}（{summary['expected_match_rate']:.1%}）")
    print(f"例外：{summary['errors']}；非法決策：{summary['illegal_decisions']}")
    print(f"重複決策一致：{summary['deterministic_cases']}/{summary['cases']}")
    print(f"決策耗時：平均 {summary['mean_ms']:.3f} ms；p95 {summary['p95_ms']:.3f} ms")
    print(f"報告：{output.resolve()}")
    return int(summary["passed_cases"] != summary["cases"])


# 固定牌例全部符合預期，候選輸出也保留在報告中
def test_fixed_case_summary():
    cases = build_cases()
    report = evaluate_cases(ActionPolicy(), cases, repeats=2)
    summary = report["summary"]
    assert summary["cases"] == summary["passed_cases"] == summary["deterministic_cases"] == 12
    assert summary["attempts"] == summary["expected_matches"] == 24
    assert summary["errors"] == summary["illegal_decisions"] == 0
    assert report["strategy_version"] == "baseline_v1"
    for case, row in zip(cases, report["cases"]):
        result = row["first_decision"]
        assert result["reason"]
        assert [item["action_id"] for item in result["candidate_evaluations"]] == [
            action.id for action in case.legal_actions
        ]


# 同 ID 的非法動作與拋例外都不能算成功，失敗耗時也要納入
def test_failures_remain_in_denominator(monkeypatch):
    case = build_cases()[0]
    action = next(a for a in case.legal_actions if a.id == case.expected_action_id)

    class BrokenPolicy:
        calls = 0

        def decide(self, observation, actions):
            self.calls += 1
            if self.calls == 3:
                raise ValueError("sample failure")
            chosen = action if self.calls == 1 else replace(action, tile=32)
            return Decision(chosen, 0.0, "sample")

    ticks = iter((0.0, 0.001, 1.0, 1.010, 2.0, 2.002))
    monkeypatch.setattr(evaluation, "perf_counter", lambda: next(ticks))
    report = evaluate_cases(BrokenPolicy(), [case], repeats=3)
    summary = report["summary"]
    assert summary["attempts"] == 3 and summary["returned_decisions"] == 2
    assert summary["errors"] == summary["illegal_decisions"] == summary["expected_matches"] == 1
    assert summary["expected_match_rate"] == pytest.approx(1 / 3)
    assert summary["passed_cases"] == summary["deterministic_cases"] == 0
    assert summary["p95_ms"] == pytest.approx(10)
    assert summary["mean_ms"] == pytest.approx(13 / 3)
    assert report["cases"][0]["errors"][0]["attempt"] == 3
    assert report["cases"][0]["unexpected_decisions"][0]["attempt"] == 2


# 動作相同但分數漂移時，也應標記為不一致
def test_changed_output_is_not_deterministic():
    case = build_cases()[0]
    action = next(a for a in case.legal_actions if a.id == case.expected_action_id)

    class ChangingPolicy:
        calls = 0

        def decide(self, observation, actions):
            self.calls += 1
            return Decision(action, float(self.calls), "changed")

    summary = evaluate_cases(ChangingPolicy(), [case], repeats=2)["summary"]
    assert summary["expected_matches"] == 2
    assert summary["passed_cases"] == summary["deterministic_cases"] == 0


# 確認命令列入口能保存可重新讀取的 JSON 摘要
def test_report_output(tmp_path):
    output = tmp_path / "summary.json"
    assert main(["--repeats", "2", "--output", str(output)]) == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["summary"]["passed_cases"] == 12
    assert len(report["metadata"]["source_sha256"]) == 64
    assert len(report["metadata"]["cases_sha256"]) == 64
    assert report["scope"] == "fixed_case_regression"


if __name__ == "__main__":
    raise SystemExit(main())