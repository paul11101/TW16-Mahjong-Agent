from dataclasses import asdict, dataclass
from math import ceil
from statistics import fmean
from time import perf_counter
from typing import Sequence

from .interfaces import Decision, LegalAction, Observation, Strategy


# 固定牌例只保存可見觀測、合法候選與預期動作
@dataclass(frozen=True)
class EvaluationCase:
    name: str
    observation: Observation
    legal_actions: tuple[LegalAction, ...]
    expected_action_id: str


# 同時統計成功與失敗嘗試，避免漏掉錯誤造成結果偏高
def evaluate_cases(
    policy: Strategy, cases: Sequence[EvaluationCase], *, repeats: int = 10,
) -> dict:
    if not isinstance(repeats, int) or repeats < 2:
        raise ValueError("repeats must be at least 2")
    cases = tuple(cases)
    if not cases:
        raise ValueError("cases cannot be empty")
    if len({case.name for case in cases}) != len(cases):
        raise ValueError("case names must be unique")
    for case in cases:
        ids = [action.id for action in case.legal_actions]
        if len(ids) != len(set(ids)) or case.expected_action_id not in ids:
            raise ValueError(f"invalid case actions: {case.name}")

    rows, durations = [], []
    for case in cases:
        first = None
        consistent = True
        returned = legal_count = matches = 0
        errors, unexpected, elapsed = [], [], []
        for index in range(repeats):
            started = perf_counter()
            try:
                decision = policy.decide(case.observation, case.legal_actions)
                if not isinstance(decision, Decision):
                    raise TypeError("policy must return Decision")
            except Exception as error:
                errors.append({"attempt": index + 1, "error": f"{type(error).__name__}: {error}"})
                continue
            finally:
                elapsed.append((perf_counter() - started) * 1000)

            returned += 1
            # 比較完整動作，不能只比較可能重複或錯用的 ID
            legal = decision.action in case.legal_actions
            legal_count += int(legal)
            matched = legal and decision.action.id == case.expected_action_id
            matches += int(matched)
            if not matched or (first is not None and decision != first):
                unexpected.append({"attempt": index + 1, "decision": asdict(decision)})
            if first is None:
                first = decision
            else:
                consistent = consistent and decision == first

        durations.extend(elapsed)
        deterministic = returned == repeats and consistent
        rows.append({
            "name": case.name,
            "expected_action_id": case.expected_action_id,
            "attempts": repeats,
            "returned_decisions": returned,
            "illegal_decisions": returned - legal_count,
            "expected_matches": matches,
            "deterministic": deterministic,
            "passed": matches == repeats and deterministic,
            "errors": errors,
            "unexpected_decisions": unexpected,
            "latency_ms": elapsed,
            "first_decision": asdict(first) if first is not None else None,
        })

    attempts = len(cases) * repeats
    matched = sum(row["expected_matches"] for row in rows)
    ordered = sorted(durations)
    return {
        "scope": "fixed_case_regression",
        "strategy_version": getattr(policy, "strategy_version", type(policy).__name__),
        "repeats": repeats,
        "timing_scope": "policy.decide, including first call and failed attempts",
        "summary": {
            "cases": len(cases),
            "passed_cases": sum(row["passed"] for row in rows),
            "attempts": attempts,
            "returned_decisions": sum(row["returned_decisions"] for row in rows),
            "errors": sum(len(row["errors"]) for row in rows),
            "illegal_decisions": sum(row["illegal_decisions"] for row in rows),
            "expected_matches": matched,
            "expected_match_rate": matched / attempts,
            "deterministic_cases": sum(row["deterministic"] for row in rows),
            "mean_ms": fmean(durations),
            # 採 nearest-rank，樣本包含每一次決策呼叫
            "p95_ms": ordered[ceil(len(ordered) * 0.95) - 1],
        },
        "cases": rows,
    }