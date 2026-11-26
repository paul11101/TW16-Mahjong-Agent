import argparse
import json
from datetime import datetime
from pathlib import Path

from src.control.model_adapter import build_policy
from src.rules.rule import RulesetConfig
from src.strategy.evaluation_plan import DEFAULT_SEEDS, build_evaluation_games
from src.strategy.run_evaluation import evaluate_policy

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MODEL = ROOT / "exports" / "strategy" / "bc_v1" / "bc_v1.pt"

def evaluate_checkpoint(checkpoint: Path, seed_count: int) -> dict:
    # 每個牌山輪換四個受測座位，三家對手沿用評測設定。
    games = build_evaluation_games(range(seed_count))
    config = RulesetConfig()
    # 整批共用同一個模型，累計各局的模型決策與代打次數。
    model = build_policy("model", checkpoint=checkpoint)
    run = evaluate_policy(
        model.strategy_version,
        games,
        config=config,
        progress=True,
        policy_factory=lambda _: model,
    )

    return {
        "model_sha256": model.checkpoint_sha256,
        "rules": config.model_dump(),
        "evaluation": run,
        "model_decisions": model.model_decisions,
        "fallback_decisions": model.fallback_decisions,
        "fallback_reasons": dict(model.fallback_reasons),
        # 所有牌局完成、有模型決策且代打為零，才列為有效的模型成績。
        "valid_model_run": (
            run["complete"] and model.model_decisions > 0 and model.fallback_decisions == 0
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="固定牌山評測 VLOG-BC 模型")
    parser.add_argument("--checkpoint", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--seed-count", type=int, default=len(DEFAULT_SEEDS))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.seed_count < 1:
        parser.error("--seed-count 必須大於 0")

    report = evaluate_checkpoint(args.checkpoint, args.seed_count)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    output = args.output or ROOT / "reports" / f"{args.checkpoint.stem}_eval_{stamp}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    run = report["evaluation"]
    print(f"完成 {run['completed']}/{run['planned']} 局，失敗 {run['failed']} 局，"
          f"Baseline 代打 {report['fallback_decisions']} 次")
    print(f"報告已儲存：{output.resolve()}")
    if not report["valid_model_run"]:
        print("本次未取得完整的純模型成績，請查看報告中的錯誤與代打原因。")
        return 1

    stats = run["summary"]
    print(f"胡牌率 {stats['win_rate']:.1%}，放槍率 {stats['deal_in_rate']:.1%}，"
          f"平均淨得分 {stats['mean_score']:.2f}，流局 {stats['draws']} 局")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())