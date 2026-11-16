import argparse
import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Callable, Sequence

from src.strategy.interfaces import Strategy
from src.rules.rule import RulesetConfig
from src.strategy.evaluation_game import play_round
from src.strategy.evaluation_metrics import EvaluationRecord, summarize_evaluation
from src.strategy.evaluation_plan import (
    POLICY_NAMES, EvaluationGame, build_evaluation_games, make_game_state, make_table_policies,
)


# 逐局記錄成功與失敗；只有完成的結算結果才交給 Day 2 統計
def evaluate_policy(
    candidate: str, games: Sequence[EvaluationGame], *,
    config: RulesetConfig | None = None, max_steps: int = 500, progress: bool = False,
    policy_factory: Callable[[EvaluationGame], Strategy] | None = None,
) -> dict:
    games = tuple(games)
    if candidate not in POLICY_NAMES and policy_factory is None:
        raise ValueError(f"unknown policy: {candidate}")
    if not games or len(set(games)) != len(games):
        raise ValueError("games must be non-empty and unique")
    if type(max_steps) is not int or max_steps < 1:
        raise ValueError("max_steps must be a positive integer")

    config = config or RulesetConfig()
    records, rows, errors = [], [], []
    for index, game in enumerate(games, start=1):
        try:
            state = make_game_state(game, config)
            # 自訂策略只替換受測座位，對手仍沿用原本配置
            policies = list(make_table_policies(
                game, candidate if candidate in POLICY_NAMES else "baseline_v1",
            ))
            if policy_factory is not None:
                policies[game.agent_seat] = policy_factory(game)

            result = play_round(state, policies, config, max_steps=max_steps)
            record = EvaluationRecord(game, result)
            rows.append({"game": asdict(game), "result": result.to_dict()})
            records.append(record)
        except Exception as error:
            errors.append({"game": asdict(game), "error": f"{type(error).__name__}: {error}"})

        if progress and (index % 25 == 0 or index == len(games)):
            print(f"{candidate}: {index}/{len(games)}, 完成 {len(records)}, 失敗 {len(errors)}",
                  flush=True)

    return {
        "candidate": candidate, "planned": len(games),
        "completed": len(records), "failed": len(errors), "complete": not errors,
        "summary": summarize_evaluation(records) if records else None,
        "rounds": rows, "errors": errors,
    }


# PyCharm 可直接執行；預設同一套 100 局設定比較兩種策略
def main() -> int:
    parser = argparse.ArgumentParser(description="固定種子的策略對戰評測")
    parser.add_argument("--seed-count", type=int, default=25)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.seed_count < 1:
        parser.error("--seed-count must be positive")

    games = build_evaluation_games(range(args.seed_count))
    config = RulesetConfig()
    runs = {
        name: evaluate_policy(name, games, config=config, progress=True)
        for name in ("random", "baseline_v1")
    }
    report = {
        "scope": "seeded_strategy_comparison",
        "rules": config.model_dump(),
        "scoring": "Rules FanCalculator basic fans; 100 points per fan",
        "win_resolution": "Rules.resolve_reaction_priority (single winner)",
        "strategies": runs,
    }
    output = args.output or (
        Path(__file__).resolve().parents[2] / "reports"
        / f"strategy_evaluation_{datetime.now():%Y%m%d_%H%M%S}.json"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    for name, run in runs.items():
        summary = run["summary"]
        if summary is not None:
            print(f"{name}: 平均得分 {summary['mean_score']:.2f}, "
                  f"胡牌率 {summary['win_rate']:.1%}, 放槍率 {summary['deal_in_rate']:.1%}")
        if run["failed"]:
            print(f"注意：{name} 有 {run['failed']} 局失敗，本次比較尚未完整。")
    print(f"結果已保存：{output.resolve()}")
    return 0 if all(run["complete"] for run in runs.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())