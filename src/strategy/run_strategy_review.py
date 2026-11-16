import argparse
import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Sequence

from src.rules.rule import RulesetConfig
from src.strategy.evaluation_plan import EvaluationGame, build_evaluation_games
from src.strategy.run_evaluation import evaluate_policy
from src.strategy.weighted_policy import DiscardWeights, WeightedPolicy


# 同一套設定各跑一次，對局與統計繼續共用 Day 3
def compare_weights(games: Sequence[EvaluationGame], weights: DiscardWeights, *,
                    progress: bool = False, max_steps: int = 500) -> dict:
    games = tuple(games)
    cases = []
    config = RulesetConfig()

    def factory(game):
        def capture(observation, actions, before, after):
            # 保存同一局面的兩種選擇，不讀取對手暗牌或牌山內容
            cases.append({
                "game": asdict(game), "observation": asdict(observation),
                "legal_actions": [asdict(action) for action in actions],
                "baseline_decision": asdict(before),
                "weighted_decision": asdict(after),
            })
        return WeightedPolicy(weights, on_change=capture)

    baseline = evaluate_policy(
        "baseline_v1", games, config=config, progress=progress, max_steps=max_steps,
    )
    weighted = evaluate_policy(
        "baseline_weighted_v1", games, config=config, progress=progress,
        max_steps=max_steps, policy_factory=factory,
    )
    return {
        "scope": "discard_weight_experiment", "weights": asdict(weights),
        "rules": config.model_dump(),
        "case_note": "Changed decisions need review; they are not proven errors.",
        "complete": baseline["complete"] and weighted["complete"],
        "baseline": baseline, "weighted": weighted, "cases": cases,
    }


# PyCharm 直接執行，預設比較 100 局原版與 100 局加權版
def main() -> int:
    parser = argparse.ArgumentParser(description="蒐集策略局面並比較棄牌權重")
    parser.add_argument("--seed-start", type=int, default=0)
    parser.add_argument("--seed-count", type=int, default=25)
    parser.add_argument("--unseen-weight", type=float, default=1.0)
    parser.add_argument("--effective-weight", type=float, default=2.0)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.seed_start < 0 or args.seed_count < 1:
        parser.error("seed-start must be non-negative and seed-count must be positive")
    try:
        weights = DiscardWeights(args.unseen_weight, args.effective_weight)
    except ValueError as error:
        parser.error(str(error))

    games = build_evaluation_games(range(args.seed_start, args.seed_start + args.seed_count))
    report = compare_weights(games, weights, progress=True)
    output = args.output or (
        Path(__file__).resolve().parents[2] / "reports"
        / f"strategy_review_{datetime.now():%Y%m%d_%H%M%S}.json"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    for name in ("baseline", "weighted"):
        run = report[name]
        summary = run["summary"]
        if summary is not None:
            print(f"{name}: 完成 {run['completed']} 局，失敗 {run['failed']} 局，"
                  f"平均得分 {summary['mean_score']:.2f}，"
                  f"胡牌率 {summary['win_rate']:.1%}，放槍率 {summary['deal_in_rate']:.1%}")
    print(f"待檢查局面：{len(report['cases'])} 筆")
    if not report["complete"]:
        print("有對局失敗，不能將本次統計視為完整比較。")
    print(f"結果已保存：{output.resolve()}")
    return 0 if report["complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())