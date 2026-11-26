import argparse
import json
from datetime import datetime
from pathlib import Path

from src.rules.rule import RulesetConfig
from src.strategy.evaluation_plan import EvaluationGame
from src.strategy.run_evaluation import evaluate_policy

REPORTS = Path(__file__).resolve().parents[2] / "reports"
DAY1_REPORT = REPORTS / "bc_v1_eval_20261127_040410_495184.json"

def compare_with_baseline(source: dict) -> dict:
    model = source["evaluation"]
    rows = model["rounds"]
    # 缺局或曾由 Baseline 代打的報告不能用來比較純模型成績。
    if (not source["valid_model_run"] or source["fallback_decisions"] != 0
            or not model["complete"] or model["failed"] != 0 or not rows
            or len(rows) != model["completed"] or len(rows) != model["planned"]):
        raise ValueError("需要完整且沒有 Baseline 代打的模型評測")

    # 沿用模型報告的規則、牌山、座位與對手，只重跑 Baseline。
    games = [EvaluationGame(**row["game"]) for row in rows]
    config = RulesetConfig.model_validate(source["rules"])
    baseline = evaluate_policy("baseline_v1", games, config=config, progress=True)
    if not baseline["complete"]:
        raise RuntimeError(f"Baseline 評測失敗: {baseline['errors'][0]}")

    # 用完整牌局設定配對，兩份報告的列順序可以不同。
    baseline_results = {EvaluationGame(**row["game"]): row["result"] for row in baseline["rounds"]}
    pairs = {"both_win": 0, "model_only": 0, "baseline_only": 0, "neither_win": 0}
    outcomes = {
        (True, True): "both_win",
        (True, False): "model_only",
        (False, True): "baseline_only",
        (False, False): "neither_win",
    }
    # 只看受測座位是否胡牌，同一組設定在四種配對結果中只算一次。
    for game, row in zip(games, rows):
        seat = game.agent_seat
        model_won = seat in row["result"]["winner_seats"]
        baseline_won = seat in baseline_results[game]["winner_seats"]
        pairs[outcomes[model_won, baseline_won]] += 1

    return {
        "model_sha256": source["model_sha256"],
        "rules": source["rules"],
        "model": model["summary"],
        "baseline": baseline["summary"],
        "paired_wins": pairs,
        "baseline_rounds": baseline["rounds"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="比較模型與 Baseline 的固定牌局成績")
    parser.add_argument("--report", type=Path, default=DAY1_REPORT)
    path = parser.parse_args().report
    result = compare_with_baseline(json.loads(path.read_text(encoding="utf-8")))
    result["model_report"] = path.name

    for key in ("model", "baseline"):
        stats = result[key]
        print(f"{key:8} | 胡牌 {stats['wins']}/{stats['games']} ({stats['win_rate']:.1%})"
              f" | 放槍 {stats['deal_ins']} | 流局 {stats['draws']}"
              f" | 平均淨得分 {stats['mean_score']:+.2f}")

    pairs = result["paired_wins"]
    print(f"都胡 {pairs['both_win']} | 只有模型胡 {pairs['model_only']} | "
          f"只有 Baseline 胡 {pairs['baseline_only']} | 都沒胡 {pairs['neither_win']}")

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    output = path.with_name(f"{path.stem}_vs_baseline_{stamp}.json")
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"比較報告：{output.resolve()}")


if __name__ == "__main__":
    main()