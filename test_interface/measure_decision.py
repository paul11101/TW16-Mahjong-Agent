"""決策耗時量測：用 SimTable 打真實對局，只量 policy.decide（不開視窗、不點擊）。

比較兩種模式（兩者選出的動作相同，差別是有沒有另外算候選評分）：
    只選牌：ActionPolicy(include_candidate_scores=False)
    預設  ：ActionPolicy()（選牌後再對所有候選重算一次評分）
企劃書預算：狀態與策略 0.3 秒（含 p95 ≤ 2 秒的其中一段）。

執行（專案根目錄）：
    python -m test_interface.measure_decision --games 20
輸出：終端機表格＋ data/processed/decision_latency.json
注意：向聽計算有 lru_cache，所以先暖機再量；實際長時間執行時快取也是熱的。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from time import perf_counter

from src.common.schemas import ActionType
from src.control.pipeline import get_reaction_rules_actions, get_turn_rules_actions
from src.strategy.action_policy import ActionPolicy
from src.strategy.adapters import actions_to_legal_actions, game_state_to_observation
from test_interface.measure_latency import stats_ms
from test_interface.sim_table import PHASE_OVER, PHASE_TURN, SimTable
from test_interface.web_observer import state_from_view

OUT_PATH = Path("data/processed/decision_latency.json")
BUDGET_MS = 300.0
MAX_STEPS = 600
SEAT = 0
SAMPLE_KEYS = ("my_turn", "reaction")


def _apply(table: SimTable, decision, legal, phase: str) -> bool:
    """把決策套到測試牌桌（等同網頁收到點擊回報）。"""
    action = decision.action
    kind = ActionType(action.action)
    if kind == ActionType.DISCARD:
        return table.agent_discard(action.tile)

    ok = table.agent_react("button", kind.value)
    siblings = [a for a in legal if a.action == action.action]
    if ok and kind in (ActionType.CHI, ActionType.KONG) and len(siblings) > 1:
        ok = table.agent_react("choice", choice_id=action.id)
    return ok


def _fallback(table: SimTable, phase: str, legal) -> bool:
    if phase == PHASE_TURN:
        first = next(a for a in legal if a.action == ActionType.DISCARD)
        return table.agent_discard(first.tile)
    return table.agent_react("button", "pass")


def play_game(seed: int, policy, samples: dict[str, list[float]]) -> int:
    """打完一局，把每次 decide 的耗時（ms）放進 samples；回傳步數。"""
    table = SimTable(seed)
    steps = 0
    while table.phase != PHASE_OVER and steps < MAX_STEPS:
        steps += 1
        phase = table.phase
        state = state_from_view(f"m{seed}", table.view(), SEAT)
        try:
            rules = (get_turn_rules_actions if phase == PHASE_TURN else get_reaction_rules_actions)(state, SEAT)
        except ValueError:
            break

        legal = actions_to_legal_actions(rules)
        if phase != PHASE_TURN and all(a.action == ActionType.PASS for a in legal):
            table.agent_react("button", "pass")  # 實際流程會略過，不算決策
            continue

        observation = game_state_to_observation(state, SEAT)
        start = perf_counter()
        decision = policy.decide(observation, legal)
        elapsed = (perf_counter() - start) * 1000.0
        samples["my_turn" if phase == PHASE_TURN else "reaction"].append(elapsed)

        if not _apply(table, decision, legal, phase) and not _fallback(table, phase, legal):
            break
    return steps


def measure(seeds, *, include_candidate_scores: bool) -> dict[str, dict[str, float]]:
    policy = ActionPolicy(include_candidate_scores=include_candidate_scores)
    samples: dict[str, list[float]] = {k: [] for k in SAMPLE_KEYS}
    for seed in seeds:
        play_game(seed, policy, samples)

    samples["all"] = samples["my_turn"] + samples["reaction"]
    return {key: stats_ms(values) for key, values in samples.items() if values}


def main() -> int:
    parser = argparse.ArgumentParser(description="決策耗時量測")
    parser.add_argument("--games", type=int, default=20)
    parser.add_argument("--seed-start", type=int, default=0)
    args = parser.parse_args()

    seeds = list(range(args.seed_start, args.seed_start + args.games))
    measure(seeds[:3], include_candidate_scores=True)  # 暖機（結果不計）

    modes = {
        "只選牌": False,
        "選牌＋候選評分（預設）": True,
    }
    results: dict[str, dict] = {}
    print(f"{'模式':<18}{'類型':<10}{'n':>6}{'平均':>9}{'p95':>9}{'最大':>9}   (ms)")
    for label, flag in modes.items():
        results[label] = measure(seeds, include_candidate_scores=flag)
        for key, s in results[label].items():
            print(f"{label:<18}{key:<10}{int(s['n']):>6}{s['mean']:>9.2f}{s['p95']:>9.2f}{s['max']:>9.2f}")

    worst = max(r["all"]["p95"] for r in results.values() if "all" in r)
    verdict = "✅ 在預算內" if worst <= BUDGET_MS else "❌ 超過預算"
    print(f"\n最差模式 p95 = {worst:.1f} ms，預算 {BUDGET_MS:.0f} ms：{verdict}")

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✅ 量測完成，已儲存：{OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())